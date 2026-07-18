(function () {
  const locale =
    (typeof navigator !== "undefined" && (navigator.language || (navigator.languages && navigator.languages[0]))) ||
    "en";

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
