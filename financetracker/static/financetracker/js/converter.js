(function () {
  const form = document.getElementById("converter-form");
  if (!form) return;

  const fromSelect = document.getElementById("converter-from");
  const toSelect = document.getElementById("converter-to");
  const amountInput = document.getElementById("converter-amount");
  const swapButton = document.getElementById("converter-swap");
  const basePath = form.getAttribute("action") || window.location.pathname;

  function buildUrl(from, to) {
    const params = new URLSearchParams();
    params.set("from", from);
    params.set("to", to);
    const amount = amountInput ? amountInput.value.trim() : "";
    if (amount) {
      params.set("amount", amount);
    }
    return `${basePath}?${params.toString()}`;
  }

  function reloadWithPair(from, to) {
    window.location.href = buildUrl(from, to);
  }

  function onCurrencyChange() {
    reloadWithPair(fromSelect.value, toSelect.value);
  }

  fromSelect.addEventListener("change", onCurrencyChange);
  toSelect.addEventListener("change", onCurrencyChange);

  swapButton.addEventListener("click", function () {
    reloadWithPair(toSelect.value, fromSelect.value);
  });
})();
