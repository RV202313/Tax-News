const fs = require('fs');
const path = require('path');

function argValue(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : undefined;
}

const profileDir = argValue('--profile-dir') || process.env.CHROME_PROFILE_DIR || path.join(__dirname, 'chrome-dev-profile');
const downloadDir = argValue('--download-dir') || process.env.DOWNLOAD_DIR || path.join(__dirname, 'pdf-downloads');
const directPreferencesPath = path.join(profileDir, 'Preferences');
const defaultPreferencesPath = path.join(profileDir, 'Default', 'Preferences');
const preferencesPath = fs.existsSync(directPreferencesPath)
  ? directPreferencesPath
  : defaultPreferencesPath;

function chromeTimeNow() {
  const windowsEpochMs = Date.UTC(1601, 0, 1);
  return String((Date.now() - windowsEpochMs) * 1000);
}

function ensureObject(parent, key) {
  if (!parent[key] || typeof parent[key] !== 'object' || Array.isArray(parent[key])) {
    parent[key] = {};
  }
  return parent[key];
}

function main() {
  if (!fs.existsSync(preferencesPath)) {
    fs.mkdirSync(path.dirname(preferencesPath), { recursive: true });
    fs.writeFileSync(preferencesPath, '{}', 'utf8');
  }

  fs.mkdirSync(downloadDir, { recursive: true });

  const prefs = JSON.parse(fs.readFileSync(preferencesPath, 'utf8'));
  const download = ensureObject(prefs, 'download');
  download.default_directory = downloadDir;
  download.prompt_for_download = false;
  download.directory_upgrade = true;

  const plugins = ensureObject(prefs, 'plugins');
  plugins.always_open_pdf_externally = true;

  const profile = ensureObject(prefs, 'profile');
  const contentSettings = ensureObject(profile, 'content_settings');
  const exceptions = ensureObject(contentSettings, 'exceptions');
  const automaticDownloads = ensureObject(exceptions, 'automatic_downloads');
  const popups = ensureObject(exceptions, 'popups');

  const lastModified = chromeTimeNow();
  for (const pattern of ['https://ras.arbitr.ru:443,*', 'https://[*.]arbitr.ru:443,*']) {
    automaticDownloads[pattern] = {
      last_modified: lastModified,
      setting: 1,
    };
    popups[pattern] = {
      last_modified: lastModified,
      setting: 1,
    };
  }

  fs.writeFileSync(preferencesPath, JSON.stringify(prefs), 'utf8');

  console.log(JSON.stringify({
    ok: true,
    preferencesPath,
    downloadDir,
    settings: {
      prompt_for_download: download.prompt_for_download,
      default_directory: download.default_directory,
      always_open_pdf_externally: plugins.always_open_pdf_externally,
      automatic_downloads: Object.keys(automaticDownloads).filter(key => key.includes('arbitr.ru')),
      popups: Object.keys(popups).filter(key => key.includes('arbitr.ru')),
    },
  }, null, 2));
}

try {
  main();
} catch (error) {
  console.error(JSON.stringify({ ok: false, error: error.message }, null, 2));
  process.exit(1);
}
