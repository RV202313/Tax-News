#!/usr/bin/env node
/* Сбор МЕТАДАННЫХ RAS через уже открытый Chrome CDP. PDF не скачиваются. */

const fs = require('fs');
const path = require('path');

function cliArgs(argv) {
  const out = {
    root: '.',
    date: new Date().toISOString().slice(0, 10),
    fixture: '',
    browserUrl: process.env.ACADEMY_RAS_BROWSER_URL || 'http://127.0.0.1:9222',
    maxQueries: 0,
  };
  for (let i = 2; i < argv.length; i++) {
    if (argv[i] === '--root') out.root = argv[++i];
    else if (argv[i] === '--date') out.date = argv[++i];
    else if (argv[i] === '--fixture') out.fixture = argv[++i];
    else if (argv[i] === '--browser-url') out.browserUrl = argv[++i];
    else if (argv[i] === '--max-queries') out.maxQueries = Number(argv[++i]) || 0;
  }
  return out;
}

function loadRasConfig(root) {
  const text = fs.readFileSync(path.join(root, 'config', 'sources.yaml'), 'utf8');
  const start = text.search(/^  - id: ru_ras\s*$/m);
  if (start < 0) throw new Error('ru_ras отсутствует в sources.yaml');
  const tail = text.slice(start);
  const next = tail.slice(1).search(/^  - id: /m);
  const block = next < 0 ? tail : tail.slice(0, next + 1);
  const queriesMatch = block.match(/queries_ru:\s*(\[[^\n]+\])/);
  const queries = queriesMatch ? JSON.parse(queriesMatch[1]) : [];
  const throttle = Number(block.match(/throttle_seconds:\s*(\d+)/)?.[1] || 20);
  const throttleMin = Number(block.match(/throttle_seconds_min:\s*(\d+)/)?.[1] || throttle);
  const throttleMax = Number(block.match(/throttle_seconds_max:\s*(\d+)/)?.[1] || throttle);
  const limit = Number(block.match(/daily_query_limit:\s*(\d+)/)?.[1] || 6);
  return {
    queries: queries.slice(0, limit),
    throttleMinMs: Math.max(1, Math.min(throttleMin, throttleMax)) * 1000,
    throttleMaxMs: Math.max(1, Math.max(throttleMin, throttleMax)) * 1000,
  };
}

function normalizeCase(value) {
  return String(value || '').toUpperCase().replace(/\s+/g, '').replace(/№/g, '');
}

function isoFromRuDate(value) {
  const match = String(value || '').match(/\b(\d{2})\.(\d{2})\.(\d{4})\b/);
  return match ? `${match[3]}-${match[2]}-${match[1]}` : '';
}

function isExplicitlyInWindow(value, fromIso, toIso) {
  if (!value) return true; // недатированное не скрываем: оно остаётся review-кандидатом
  return value >= fromIso && value <= toIso;
}

function caseFromText(value) {
  return String(value || '').match(/[АA]\d{1,3}-\d+\/\d{4}/i)?.[0] || '';
}

function caseAndDateFromUrl(value) {
  const raw = String(value || '');
  if (!raw) return { caseNumber: '', publishedAt: '' };
  const tail = raw.split('/').pop() || '';
  let decoded = tail;
  try {
    decoded = decodeURIComponent(tail);
  } catch (_) {}
  const match = decoded.match(/([АA]\d{1,3}-\d+(?:-\d{4}|\/\d{4}))__([12]\d{3})(\d{2})(\d{2})/i);
  if (!match) return { caseNumber: '', publishedAt: '' };
  const normalizedCase = match[1].replace(/-(\d{4})$/, '/$1');
  return { caseNumber: normalizedCase, publishedAt: `${match[2]}-${match[3]}-${match[4]}` };
}

function buildItem(row, query, classifyRasRow) {
  const rowText = String(row.rowText || row.text || '').replace(/\s+/g, ' ').trim();
  const fromUrl = caseAndDateFromUrl(row.href || '');
  const caseNumber = row.caseNumber || caseFromText(rowText) || fromUrl.caseNumber;
  const decision = classifyRasRow({ href: row.href || '', text: row.text || '', rowText });
  if (decision.action === 'skip') return null;
  const act = normalizeCase(caseNumber);
  return {
    url: row.href || '',
    ecli: '',
    act,
    case_number: caseNumber,
    title: caseNumber ? `Арбитражное дело ${caseNumber}: ${query}` : `Арбитражный акт: ${query}`,
    summary: rowText,
    published_at: isoFromRuDate(row.date || rowText) || fromUrl.publishedAt,
    court: row.court || '',
    query,
    item_type: 'court_decision',
    review_flag: decision.reviewFlag || '',
    review_reason: decision.reviewReason || '',
  };
}

function writeOutput(root, runDate, items, metadata = {}) {
  const outDir = path.join(root, 'pipeline', 'raw', runDate);
  fs.mkdirSync(outDir, { recursive: true });
  const target = path.join(outDir, 'ru_ras_1.txt');
  fs.writeFileSync(target, JSON.stringify({ date: runDate, items, ...metadata }, null, 2), 'utf8');
  return target;
}

function sleep(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }

function randomBetween(min, max) {
  if (max <= min) return min;
  return min + Math.floor(Math.random() * (max - min + 1));
}

async function setInput(page, element, value) {
  // RAS привязывает model к keyboard/input-событиям. Простое
  // node.value=... меняет DOM, но в POST уходит пустое значение.
  await element.click({ clickCount: 3 });
  await element.press('Backspace');
  await element.type(value, { delay: 15 });
  await element.press('Tab');
}

async function findSearchPage(browser) {
  const pages = await browser.pages();
  for (const page of pages) {
    if (page.url().startsWith('https://ras.arbitr.ru/')) {
      // CDP может отдать page раньше, чем JS достроит форму.
      // Без этого живой запуск гоночно видел пустой body.
      await page.waitForSelector('textarea[placeholder*="текст" i]', { timeout: 30000 });
      return page;
    }
  }
  throw Object.assign(new Error('откройте вкладку https://ras.arbitr.ru/ в CDP-Chrome'), { manual: true });
}

async function runSearch(page, query, fromDate, toDate) {
  await page.evaluate(() => {
    document.querySelector('.b-promo_notification-popup-close')?.click();
  }).catch(() => {});
  const textInput = await page.$('textarea[placeholder*="текст" i], input[placeholder*="текст документа" i], textarea');
  if (!textInput) throw new Error('не найдено поле «текст документа»');
  await setInput(page, textInput, query);
  const dateInputs = await page.$$('input[placeholder*="дд.мм.гггг" i]');
  if (dateInputs.length < 2) throw new Error('не найдены поля периода поиска');
  await setInput(page, dateInputs[dateInputs.length - 2], fromDate);
  await setInput(page, dateInputs[dateInputs.length - 1], toDate);
  const responsePromise = page.waitForResponse(
    response => /\/Ras\/Search/i.test(response.url()),
    { timeout: 45000 },
  ).catch(() => null);
  const clicked = await page.evaluate(() => {
    const controls = [...document.querySelectorAll('button, input[type="submit"], a')];
    const button = controls.find(node => /(^|\s)найти(\s|$)/i.test((node.innerText || node.value || '').trim()));
    if (button) { button.click(); return true; }
    return false;
  });
  if (!clicked) await dateInputs[dateInputs.length - 1].press('Enter');
  await responsePromise;
  await page.waitForFunction(
    () => document.querySelectorAll('a.js-popupDocumentShow').length > 0
      || Number(document.querySelector('#totalCount')?.textContent || 0) === 0
      || /Найдено\s+0/i.test(document.body.innerText || ''),
    { timeout: 15000 },
  );
  return page.evaluate(() => [...document.querySelectorAll('a.js-popupDocumentShow')].map(anchor => {
    const row = anchor.closest('tr') || anchor.parentElement;
    const rowText = (row?.innerText || '').trim();
    const caseAnchor = row?.querySelector('a[href*="/Card/"]');
    return {
      href: anchor.href,
      text: (anchor.innerText || '').trim(),
      rowText,
      caseNumber: (caseAnchor?.innerText || '').trim(),
      date: rowText.match(/\b\d{2}\.\d{2}\.\d{4}\b/)?.[0] || '',
      court: (row?.querySelector('[class*="court" i]')?.innerText || '').trim(),
    };
  }));
}

async function main() {
  const args = cliArgs(process.argv);
  const root = path.resolve(args.root);
  const external = path.resolve(__dirname, '..', '..', 'arbitr.ru');
  const { classifyRasRow } = require(path.join(external, 'ras_title_rules.js'));
  if (args.fixture) {
    const payload = JSON.parse(fs.readFileSync(args.fixture, 'utf8'));
    const rows = Array.isArray(payload) ? payload : payload.rows || [];
    const query = payload.query || 'тестовый запрос';
    const items = rows.map(row => buildItem(row, query, classifyRasRow)).filter(Boolean);
    console.log(`[ras] fixture: ${items.length} items → ${writeOutput(root, args.date, items, { fixture: true })}`);
    return;
  }

  const puppeteer = require(path.join(external, 'node_modules', 'puppeteer-core'));
  const loaded = loadRasConfig(root);
  const queries = args.maxQueries > 0 ? loaded.queries.slice(0, args.maxQueries) : loaded.queries;
  const { throttleMinMs, throttleMaxMs } = loaded;
  const end = new Date(`${args.date}T12:00:00Z`);
  const start = new Date(end); start.setUTCDate(start.getUTCDate() - 6);
  const ruDate = value => `${String(value.getUTCDate()).padStart(2, '0')}.${String(value.getUTCMonth() + 1).padStart(2, '0')}.${value.getUTCFullYear()}`;
  let browser;
  try {
    browser = await puppeteer.connect({ browserURL: args.browserUrl, defaultViewport: null, protocolTimeout: 120000 });
    const page = await findSearchPage(browser);
    const items = [];
    const seenCases = new Set();
    const attempts = [];
    let outOfWindow = 0;
    const fromIso = start.toISOString().slice(0, 10);
    const toIso = end.toISOString().slice(0, 10);
    for (let index = 0; index < queries.length; index++) {
      if (index) await sleep(randomBetween(throttleMinMs, throttleMaxMs));
      const query = queries[index];
      const rows = await runSearch(page, query, ruDate(start), ruDate(end));
      attempts.push({ query, results: rows.length });
      for (const row of rows) {
        const item = buildItem(row, query, classifyRasRow);
        if (!item) continue;
        if (!isExplicitlyInWindow(item.published_at, fromIso, toIso)) {
          outOfWindow += 1;
          continue;
        }
        const key = item.act || item.url;
        if (key && seenCases.has(key)) continue;
        if (key) seenCases.add(key);
        items.push(item);
      }
      if (rows.length) break; // дополнительные запросы только если главный пуст
    }
    console.log(`[ras] ${items.length} items → ${writeOutput(root, args.date, items, {
      attempts,
      query_window: { from: fromIso, to: toIso },
      out_of_window_discarded: outOfWindow,
    })}`);
  } catch (error) {
    if (/browserURL|webSocket URL|404|Not Found|ECONNREFUSED|откройте вкладку/i.test(error.message) || error.manual) {
      console.error(`[ras] CDP_UNAVAILABLE: ${error.message}`);
      process.exitCode = 3;
    } else {
      throw error;
    }
  } finally {
    if (browser) await browser.disconnect().catch(() => {});
  }
}

if (require.main === module) {
  main().catch(error => { console.error(`[ras] ${error.stack || error.message}`); process.exit(1); });
}

module.exports = { buildItem, normalizeCase, isoFromRuDate, isExplicitlyInWindow, loadRasConfig };
