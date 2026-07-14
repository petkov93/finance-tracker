(function () {
  const select = document.getElementById("id_default_currency");
  const supported = window.FINANCE_TRACKER_SUPPORTED_CURRENCIES;

  if (!select || !Array.isArray(supported) || supported.length === 0) {
    return;
  }

  const supportedSet = new Set(supported.map((code) => code.toUpperCase()));

  const REGION_TO_CURRENCY = {
    AD: "EUR",
    AE: "AED",
    AG: "XCD",
    AL: "ALL",
    AM: "AMD",
    AR: "ARS",
    AT: "EUR",
    AU: "AUD",
    AW: "AWG",
    AZ: "AZN",
    BA: "BAM",
    BB: "BBD",
    BE: "EUR",
    BG: "BGN",
    BH: "BHD",
    BM: "BMD",
    BN: "BND",
    BO: "BOB",
    BR: "BRL",
    BS: "BSD",
    BW: "BWP",
    BY: "BYN",
    BZ: "BZD",
    CA: "CAD",
    CH: "CHF",
    CL: "CLP",
    CN: "CNY",
    CO: "COP",
    CR: "CRC",
    CU: "CUP",
    CY: "EUR",
    CZ: "CZK",
    DE: "EUR",
    DK: "DKK",
    DO: "DOP",
    DZ: "DZD",
    EC: "USD",
    EE: "EUR",
    EG: "EGP",
    ES: "EUR",
    FI: "EUR",
    FJ: "FJD",
    FR: "EUR",
    GB: "GBP",
    GE: "GEL",
    GH: "GHS",
    GI: "GIP",
    GR: "EUR",
    GT: "GTQ",
    GY: "GYD",
    HK: "HKD",
    HN: "HNL",
    HR: "EUR",
    HU: "HUF",
    ID: "IDR",
    IE: "EUR",
    IL: "ILS",
    IN: "INR",
    IS: "ISK",
    IT: "EUR",
    JM: "JMD",
    JO: "JOD",
    JP: "JPY",
    KE: "KES",
    KG: "KGS",
    KH: "KHR",
    KR: "KRW",
    KW: "KWD",
    KY: "KYD",
    KZ: "KZT",
    LB: "LBP",
    LI: "CHF",
    LK: "LKR",
    LT: "EUR",
    LU: "EUR",
    LV: "EUR",
    MA: "MAD",
    MC: "EUR",
    MD: "MDL",
    ME: "EUR",
    MK: "MKD",
    MT: "EUR",
    MU: "MUR",
    MX: "MXN",
    MY: "MYR",
    MZ: "MZN",
    NG: "NGN",
    NI: "NIO",
    NL: "EUR",
    NO: "NOK",
    NP: "NPR",
    NZ: "NZD",
    OM: "OMR",
    PA: "PAB",
    PE: "PEN",
    PH: "PHP",
    PK: "PKR",
    PL: "PLN",
    PT: "EUR",
    PY: "PYG",
    QA: "QAR",
    RO: "RON",
    RS: "RSD",
    RU: "RUB",
    SA: "SAR",
    SE: "SEK",
    SG: "SGD",
    SI: "EUR",
    SK: "EUR",
    SM: "EUR",
    SR: "SRD",
    SV: "SVC",
    TH: "THB",
    TN: "TND",
    TR: "TRY",
    TT: "TTD",
    TW: "TWD",
    TZ: "TZS",
    UA: "UAH",
    US: "USD",
    UY: "UYU",
    UZ: "UZS",
    VE: "VES",
    VN: "VND",
    XK: "EUR",
    ZA: "ZAR",
  };

  function regionFromLocale(locale) {
    if (!locale) {
      return null;
    }

    const normalized = locale.replace(/_/g, "-");
    const parts = normalized.split("-");
    if (parts.length < 2) {
      return null;
    }

    const region = parts[parts.length - 1].toUpperCase();
    return /^[A-Z]{2}$/.test(region) ? region : null;
  }

  function suggestCurrencyFromLocale() {
    const locales = navigator.languages && navigator.languages.length
      ? navigator.languages
      : [navigator.language];

    for (const locale of locales) {
      const region = regionFromLocale(locale);
      if (!region) {
        continue;
      }

      const currency = REGION_TO_CURRENCY[region];
      if (currency && supportedSet.has(currency)) {
        return currency;
      }
    }

    return null;
  }

  if (select.value) {
    return;
  }

  const suggested = suggestCurrencyFromLocale();
  if (suggested) {
    select.value = suggested;
  }
})();
