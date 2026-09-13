const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');
const { classifyRasRow } = require('./ras_title_rules');

const port = Number(process.env.CHROME_REMOTE_DEBUGGING_PORT || 9222);
const downloadDir = process.env.DOWNLOAD_DIR || path.join(__dirname, 'pdf-downloads');
const manifestPath = process.env.MANIFEST_PATH || path.join(__dirname, 'ras_all_download_manifest.json');
const minDelayMs = Number(process.env.DOWNLOAD_DELAY_MIN_MS || 15000);
const maxDelayMs = Number(process.env.DOWNLOAD_DELAY_MAX_MS || 25000);
const maxPages = Number(process.env.MAX_PAGES || 0);
const maxDownloads = Number(process.env.MAX_DOWNLOADS || 0);
const disableTitleFilter = process.env.DISABLE_TITLE_FILTER === '1';
const forceDownloadParam = process.env.FORCE_DOWNLOAD_PARAM === '1';
const directResponseDownload = process.env.DIRECT_RESPONSE_DOWNLOAD === '1';
const skipPreviousErrors = process.env.SKIP_PREVIOUS_ERRORS === '1';
const skipDuplicateBaseName = process.env.SKIP_DUPLICATE_BASENAME === '1';

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function randomDelayMs() {
  const min = Math.min(minDelayMs, maxDelayMs);
  const max = Math.max(minDelayMs, maxDelayMs);
  return min + Math.floor(Math.random() * (max - min + 1));
}

function fileNameFromPdfUrl(href) {
  return decodeURIComponent(new URL(href).pathname.split('/').pop());
}

function collisionSafePath(href) {
  const url = new URL(href);
  const parts = url.pathname.split('/').filter(Boolean);
  const baseName = decodeURIComponent(parts.at(-1));
  const basePath = path.join(downloadDir, baseName);
  if (!fs.existsSync(basePath)) return { fileName: baseName, filePath: basePath };
  if (skipDuplicateBaseName) return { fileName: baseName, filePath: basePath };

  const documentId = parts.at(-2) || 'duplicate';
  const parsed = path.parse(baseName);
  const uniqueName = `${parsed.name}__${documentId.slice(0, 8)}${parsed.ext || '.pdf'}`;
  return { fileName: uniqueName, filePath: path.join(downloadDir, uniqueName) };
}

function loadManifest() {
  if (!fs.existsSync(manifestPath)) {
    return { startedAt: new Date().toISOString(), downloadDir, files: [], skippedByTitle: [], errors: [] };
  }
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
  manifest.files ||= [];
  manifest.skippedByTitle ||= [];
  manifest.errors ||= [];
  return manifest;
}

function saveManifest(manifest) {
  manifest.updatedAt = new Date().toISOString();
  fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2), 'utf8');
}

async function waitForDownload(filePath, timeoutMs = 90000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (fs.existsSync(filePath) && !fs.existsSync(`${filePath}.crdownload`)) {
      const stat = fs.statSync(filePath);
      if (stat.size > 1000) return stat;
    }
    await sleep(500);
  }
  throw new Error(`Timed out waiting for ${filePath}`);
}

async function getResultsPage(browser) {
  const pages = await browser.pages();
  for (const page of pages.filter(page => page.url().startsWith('https://ras.arbitr.ru/'))) {
    const state = await page.evaluate(() => ({
      found: /Найдено\s+\d+/i.test(document.body.innerText || ''),
      pdfLinks: document.querySelectorAll('a[href*="/Kad/PdfDocument/"]').length,
    })).catch(() => ({ found: false, pdfLinks: 0 }));
    if (state.pdfLinks || state.found) return page;
  }
  throw new Error('ras.arbitr.ru results page is not open');
}

async function readPageState(page) {
  return page.evaluate(() => {
    const total = Number(document.querySelector('#totalCount')?.textContent || 0);
    const active = Number(document.querySelector('#pages li.active a')?.textContent || 1);
    const links = [...document.querySelectorAll('a.js-popupDocumentShow[href*="/Kad/PdfDocument/"]')]
      .map(a => ({
        href: a.href,
        text: (a.innerText || '').trim(),
        rowText: (a.closest('tr')?.innerText || a.parentElement?.innerText || '').trim(),
      }));
    return {
      total,
      active,
      pageCount: Math.ceil(total / 25) || 1,
      firstHref: links[0]?.href || '',
      links,
    };
  });
}

async function goToPage(page, pageNumber) {
  let state = await readPageState(page);
  if (state.active === pageNumber) return state;

  for (let attempt = 0; attempt < 6; attempt++) {
    state = await readPageState(page);
    const previousFirstHref = state.firstHref;
    const clicked = await page.evaluate(target => {
      const exact = document.querySelector(`#pages a[href="#page${target}"]`);
      if (exact) {
        exact.click();
        return true;
      }
      const visiblePages = [...document.querySelectorAll('#pages a[href^="#page"]')]
        .map(a => Number((a.getAttribute('href') || '').replace('#page', '')))
        .filter(Boolean);
      if (!visiblePages.length) return false;
      const nearest = visiblePages.reduce((best, value) => Math.abs(value - target) < Math.abs(best - target) ? value : best, visiblePages[0]);
      document.querySelector(`#pages a[href="#page${nearest}"]`)?.click();
      return true;
    }, pageNumber);
    if (!clicked) throw new Error(`Could not find pagination control for page ${pageNumber}`);

    const deadline = Date.now() + 45000;
    while (Date.now() < deadline) {
      await sleep(500);
      state = await readPageState(page);
      if (state.active === pageNumber && state.links.length && state.firstHref !== previousFirstHref) {
        return state;
      }
      if (state.active === pageNumber && state.links.length && pageNumber === 1) {
        return state;
      }
    }
  }
  throw new Error(`Timed out opening page ${pageNumber}`);
}

async function downloadPdf(browser, href) {
  const { fileName, filePath } = collisionSafePath(href);
  if (fs.existsSync(filePath) && fs.statSync(filePath).size > 1000) {
    return { fileName, filePath, skipped: true, bytes: fs.statSync(filePath).size };
  }

  fs.rmSync(`${filePath}.crdownload`, { force: true });
  const tab = await browser.newPage();
  const cdp = await tab.target().createCDPSession();
  await cdp.send('Browser.setDownloadBehavior', { behavior: 'allow', downloadPath: downloadDir });
  try {
    const downloadHref = forceDownloadParam
      ? `${href}${href.includes('?') ? '&' : '?'}download=true`
      : href;
    const response = await tab.goto(downloadHref, { waitUntil: 'domcontentloaded', timeout: 30000 }).catch(error => {
      if (directResponseDownload) throw error;
      return null;
    });
    if (directResponseDownload && response) {
      const buffer = await response.buffer();
      if (buffer.length <= 1000) {
        throw new Error(`Downloaded response is too small for ${href}: ${buffer.length} bytes`);
      }
      fs.writeFileSync(filePath, buffer);
      return { fileName, filePath, skipped: false, bytes: buffer.length };
    }
    const stat = await waitForDownload(filePath);
    return { fileName, filePath, skipped: false, bytes: stat.size };
  } finally {
    await tab.close().catch(() => {});
  }
}

async function main() {
  fs.mkdirSync(downloadDir, { recursive: true });
  const browser = await puppeteer.connect({
    browserURL: `http://127.0.0.1:${port}`,
    defaultViewport: null,
    protocolTimeout: 120000,
  });
  const manifest = loadManifest();
  const seen = new Set([
    ...manifest.files.map(file => file.href),
    ...manifest.skippedByTitle.map(file => file.href),
    ...(skipPreviousErrors ? manifest.errors.map(file => file.href) : []),
  ]);
  let downloadedOrSkipped = manifest.files.length;

  try {
    const page = await getResultsPage(browser);
    const cdp = await page.target().createCDPSession();
    await cdp.send('Browser.setDownloadBehavior', { behavior: 'allow', downloadPath: downloadDir });

    const initial = await readPageState(page);
    const pageCount = maxPages ? Math.min(maxPages, initial.pageCount) : initial.pageCount;
    manifest.currentSearchTotal = initial.total;
    manifest.currentSearchPageCount = initial.pageCount;
    manifest.total = Math.max(Number(manifest.total || 0), initial.total);
    manifest.pageCount = Math.max(Number(manifest.pageCount || 0), initial.pageCount);
    saveManifest(manifest);

    for (let pageNumber = 1; pageNumber <= pageCount; pageNumber++) {
      const state = await goToPage(page, pageNumber);
      console.log(`page ${pageNumber}/${pageCount}: ${state.links.length} pdf links`);
      manifest.lastPageStarted = pageNumber;
      saveManifest(manifest);

      for (const [index, link] of state.links.entries()) {
        if (maxDownloads && downloadedOrSkipped >= maxDownloads) {
          saveManifest(manifest);
          console.log(`MAX_DOWNLOADS reached: ${maxDownloads}`);
          return;
        }
        if (seen.has(link.href)) continue;

        try {
          const titleDecision = disableTitleFilter
            ? { action: 'download', reviewFlag: false, reviewReason: null }
            : classifyRasRow(link);
          if (titleDecision.action === 'skip') {
            seen.add(link.href);
            manifest.skippedByTitle.push({
              page: pageNumber,
              indexOnPage: index + 1,
              href: link.href,
              text: link.text,
              rowText: link.rowText,
              rule: titleDecision.hardRule,
              reason: titleDecision.reason,
            });
            saveManifest(manifest);
            console.log(`title-skip page ${pageNumber} item ${index + 1}: ${titleDecision.reason}`);
            continue;
          }

          const result = await downloadPdf(browser, link.href);
          seen.add(link.href);
          downloadedOrSkipped++;
          manifest.files.push({
            page: pageNumber,
            indexOnPage: index + 1,
            href: link.href,
            file: result.filePath,
            bytes: result.bytes,
            skippedExisting: result.skipped,
            reviewFlag: titleDecision.reviewFlag,
            reviewReason: titleDecision.reviewReason,
            text: link.text,
            rowText: link.rowText,
          });
          saveManifest(manifest);
          console.log(`${result.skipped ? 'skipped' : 'downloaded'} ${downloadedOrSkipped}/${initial.total}: ${result.fileName}`);
          if (!result.skipped) {
            const pause = randomDelayMs();
            console.log(`pause ${Math.round(pause / 1000)}s`);
            await sleep(pause);
          }
        } catch (error) {
          manifest.errors.push({
            page: pageNumber,
            indexOnPage: index + 1,
            href: link.href,
            error: error.message,
          });
          saveManifest(manifest);
          console.log(`error page ${pageNumber} item ${index + 1}: ${error.message}`);
        }
      }
      manifest.lastPageCompleted = pageNumber;
      saveManifest(manifest);
    }
    const resolvedHrefs = new Set([
      ...manifest.files.map(file => file.href),
      ...manifest.skippedByTitle.map(file => file.href),
    ]);
    const unresolvedErrors = manifest.errors.filter(error => !resolvedHrefs.has(error.href));
    if (!unresolvedErrors.length) {
      manifest.completedAt = new Date().toISOString();
    }
    saveManifest(manifest);
  } finally {
    saveManifest(manifest);
    await browser.disconnect();
  }
}

main().catch(error => {
  console.error(JSON.stringify({ ok: false, error: error.message, stack: error.stack }, null, 2));
  process.exit(1);
});
