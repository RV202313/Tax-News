#!/usr/bin/env node
/* Скачать все PDF RAS из текущего сырья дня через уже открытый CDP-Chrome.
 * Сохраняет ВСЕ загруженные PDF в root/court_analysis/extracted_text/ras/{date}/
 * и manifest.json. Итоговая фильтрация substantive/procedural выполняется
 * отдельным Python-этапом court_protocol.py.
 */

const fs = require('fs');
const path = require('path');
const puppeteer = require(path.join(__dirname, '..', '..', 'arbitr.ru', 'node_modules', 'puppeteer-core'));

function cliArgs(argv) {
  const out = {
    root: '.',
    date: new Date().toISOString().slice(0, 10),
    browserUrl: process.env.ACADEMY_RAS_BROWSER_URL || 'http://127.0.0.1:9222',
    minDelayMs: 15000,
    maxDelayMs: 25000,
  };
  for (let i = 2; i < argv.length; i++) {
    if (argv[i] === '--root') out.root = argv[++i];
    else if (argv[i] === '--date') out.date = argv[++i];
    else if (argv[i] === '--browser-url') out.browserUrl = argv[++i];
    else if (argv[i] === '--min-delay-ms') out.minDelayMs = Number(argv[++i]) || out.minDelayMs;
    else if (argv[i] === '--max-delay-ms') out.maxDelayMs = Number(argv[++i]) || out.maxDelayMs;
  }
  return out;
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function randomDelayMs(minMs, maxMs) {
  const min = Math.min(minMs, maxMs);
  const max = Math.max(minMs, maxMs);
  return min + Math.floor(Math.random() * (max - min + 1));
}

function analysisRoot(root) {
  const project = path.resolve(root);
  return path.basename(project) === 'News Claude'
    ? path.join(path.dirname(project), 'court_analysis')
    : path.join(project, 'court_analysis');
}

function safeCaseName(value) {
  return String(value || '').replace(/[^\p{L}\p{N}._-]+/gu, '_').replace(/^_+|_+$/g, '') || 'ras_case';
}

function inputItems(root, runDate) {
  const file = path.join(root, 'pipeline', 'raw', runDate, 'ru_ras_1.txt');
  const payload = JSON.parse(fs.readFileSync(file, 'utf8'));
  return Array.isArray(payload.items) ? payload.items : [];
}

async function downloadPdf(browser, href, targetPath) {
  const page = await browser.newPage();
  try {
    const response = await page.goto(href, { waitUntil: 'networkidle2', timeout: 60000 });
    if (!response) throw new Error('empty response');
    const buffer = await response.buffer();
    if (!buffer || buffer.length < 1000 || buffer.slice(0, 5).toString() !== '%PDF-') {
      throw new Error(`not a PDF response (${buffer ? buffer.length : 0} bytes)`);
    }
    fs.writeFileSync(targetPath, buffer);
    return buffer.length;
  } finally {
    await page.close().catch(() => {});
  }
}

async function main() {
  const args = cliArgs(process.argv);
  const root = path.resolve(args.root);
  const base = path.join(analysisRoot(root), 'extracted_text', 'ras', args.date);
  fs.mkdirSync(base, { recursive: true });
  const items = inputItems(root, args.date);
  const manifest = { date: args.date, items: [] };
  let browser;
  try {
    browser = await puppeteer.connect({ browserURL: args.browserUrl, defaultViewport: null, protocolTimeout: 120000 });
    for (let index = 0; index < items.length; index++) {
      const item = items[index];
      const caseNumber = item.case_number || item.act || `row_${index + 1}`;
      const stem = `${safeCaseName(caseNumber)}__${item.published_at || args.date}`;
      const target = path.join(base, `${stem}.pdf`);
      try {
        const bytes = fs.existsSync(target) && fs.statSync(target).size > 1000
          ? fs.statSync(target).size
          : await downloadPdf(browser, item.url, target);
        manifest.items.push({
          case_number: caseNumber,
          decision_date: item.published_at || '',
          url: item.url,
          pdf_path: target,
          state: 'ok',
          bytes,
        });
      } catch (error) {
        manifest.items.push({
          case_number: caseNumber,
          decision_date: item.published_at || '',
          url: item.url,
          state: 'failed',
          error: String(error && error.message || error),
        });
      }
      if (index + 1 < items.length) {
        await sleep(randomDelayMs(args.minDelayMs, args.maxDelayMs));
      }
    }
  } catch (error) {
    console.error(`[ras-full] CDP_UNAVAILABLE: ${error.message}`);
    process.exitCode = 3;
  } finally {
    if (browser) await browser.disconnect().catch(() => {});
  }
  const manifestPath = path.join(base, 'manifest.json');
  fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2), 'utf8');
  const ok = manifest.items.filter(item => item.state === 'ok').length;
  const failed = manifest.items.filter(item => item.state === 'failed').length;
  console.log(`[ras-full] OK=${ok} FAILED=${failed} → ${manifestPath}`);
}

if (require.main === module) {
  main().catch(error => {
    console.error(`[ras-full] ${error.stack || error.message}`);
    process.exit(1);
  });
}
