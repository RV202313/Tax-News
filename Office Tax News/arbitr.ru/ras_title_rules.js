function normalizeTitle(value) {
  return String(value || '')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase()
    .replace(/ё/g, 'е');
}

function safeDecode(value) {
  try {
    return decodeURIComponent(String(value || ''));
  } catch {
    return String(value || '');
  }
}

const hardSkipRules = [
  {
    id: 'sip_intellectual_property',
    reason: 'СИП / Суд по интеллектуальным правам',
    patterns: [
      /суд по интеллектуальным правам/i,
      /(^|[^а-яa-z0-9])сип-\d+/i,
    ],
  },
  {
    id: 'personal_bankruptcy_realization',
    reason: 'персональное банкротство гражданина / реализация имущества',
    patterns: [
      /реализац[а-яa-z0-9_-]* имущества гражданин/i,
      /освобод[а-яa-z0-9_-]* гражданин[а-яa-z0-9_-]* от исполнения обязательств/i,
      /ст\.?\s*213\.28/i,
    ],
  },
  {
    id: 'no_debt_release_rule',
    reason: 'неприменение правила освобождения гражданина от долгов',
    patterns: [
      /неприменен[а-яa-z0-9_-]* правил[а-яa-z0-9_-]* об освобожден[а-яa-z0-9_-]* гражданин[а-яa-z0-9_-]* от исполнения обязательств/i,
    ],
  },
  {
    id: 'creditors_register',
    reason: 'реестр требований кредиторов',
    patterns: [
      /включен[а-яa-z0-9_-]* требован[а-яa-z0-9_-]* в реестр требован[а-яa-z0-9_-]* кредитор/i,
      /отказ[а-яa-z0-9_-]* во включен[а-яa-z0-9_-]* требован[а-яa-z0-9_-]* в реестр/i,
      /реестр требован[а-яa-z0-9_-]* кредитор/i,
    ],
  },
  {
    id: 'administrative_fine',
    reason: 'административное правонарушение / штраф',
    patterns: [
      /административн[а-яa-z0-9_-]* правонарушен/i,
      /(^|[^а-яa-z])штраф/i,
    ],
  },
  {
    id: 'state_duty_return',
    reason: 'возврат госпошлины',
    patterns: [
      /возврат[а-яa-z0-9_-]* государственн[а-яa-z0-9_-]* пошлин/i,
      /возврат[а-яa-z0-9_-]* госпошлин/i,
      /возвратить государственн[а-яa-z0-9_-]* пошлин/i,
      /возвратить госпошлин/i,
    ],
  },
  {
    id: 'deposit_account_payment',
    reason: 'депозитный счет / выплата с депозита',
    patterns: [
      /депозитн[а-яa-z0-9_-]* счет/i,
      /выплат[а-яa-z0-9_-]* с депозитн[а-яa-z0-9_-]* счет/i,
      /выплат[а-яa-z0-9_-]* из федеральн[а-яa-z0-9_-]* бюджет/i,
    ],
  },
  {
    id: 'manager_remuneration',
    reason: 'вознаграждение управляющего',
    patterns: [
      /вознагражден[а-яa-z0-9_-]* арбитражн[а-яa-z0-9_-]* управляющ/i,
      /вознагражден[а-яa-z0-9_-]* финансов[а-яa-z0-9_-]* управляющ/i,
      /ст\.?\s*109\b/i,
    ],
  },
];

const softMarkRules = [
  {
    id: 'money_collection',
    reason: 'обычное взыскание денежных средств',
    patterns: [
      /взыск[а-яa-z0-9_-]* денежн[а-яa-z0-9_-]* средств/i,
      /удовлетворить требован[а-яa-z0-9_-]*:\s*взыск/i,
    ],
  },
  {
    id: 'broad_bankruptcy',
    reason: 'банкротство в широком смысле',
    patterns: [
      /банкротств/i,
      /несостоятельност/i,
      /оспариван[а-яa-z0-9_-]* сдел[а-яa-z0-9_-]* должник/i,
      /ст\.?\s*61\.1/i,
      /ст\.?\s*213\.11/i,
    ],
  },
  {
    id: 'court_costs',
    reason: 'судебные расходы',
    patterns: [
      /судебн[а-яa-z0-9_-]* расход/i,
      /возмест[а-яa-z0-9_-]* судебн[а-яa-z0-9_-]* расход/i,
    ],
  },
];

function matchRules(rules, rawText) {
  const text = normalizeTitle(rawText);
  for (const rule of rules) {
    if (rule.patterns.some(pattern => pattern.test(text))) {
      return {
        id: rule.id,
        reason: rule.reason,
      };
    }
  }
  return null;
}

function classifyRasRow(link) {
  const rawText = [
    link?.rowText,
    link?.text,
    link?.href,
    safeDecode(link?.href),
  ].filter(Boolean).join(' ');
  const hard = matchRules(hardSkipRules, rawText);
  if (hard) {
    return {
      action: 'skip',
      hardRule: hard.id,
      reason: hard.reason,
      reviewFlag: null,
    };
  }

  const soft = matchRules(softMarkRules, rawText);
  if (soft) {
    return {
      action: 'download',
      hardRule: null,
      reason: null,
      reviewFlag: soft.id,
      reviewReason: soft.reason,
    };
  }

  return {
    action: 'download',
    hardRule: null,
    reason: null,
    reviewFlag: null,
  };
}

module.exports = {
  classifyRasRow,
  hardSkipRules,
  softMarkRules,
};
