(function () {
  function resolveLocale() {
    if (window.FINANCE_TRACKER_DISPLAY_LOCALE) {
      return window.FINANCE_TRACKER_DISPLAY_LOCALE;
    }
    if (typeof navigator !== "undefined") {
      return navigator.language || (navigator.languages && navigator.languages[0]) || "en";
    }
    return "en";
  }

  const locale = resolveLocale();

  function formatAmount(amount, decimalPlaces) {
    const digits = decimalPlaces == null ? 2 : decimalPlaces;
    return Number(amount).toLocaleString(locale, {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
      useGrouping: true,
    });
  }

  function formatMoney(amount, currency, decimalPlaces) {
    return formatAmount(amount, decimalPlaces) + " " + String(currency).toUpperCase();
  }

  window.FinanceTrackerMoney = {
    locale: locale,
    formatAmount: formatAmount,
    formatMoney: formatMoney,
  };
})();
