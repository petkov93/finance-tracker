(function () {
  const form = document.getElementById("converter-form");
  if (!form) return;

  const rateUrl = form.dataset.rateUrl;
  const convertUrl = form.dataset.convertUrl;
  const csrfInput = form.querySelector("[name=csrfmiddlewaretoken]");
  const csrfToken = csrfInput ? csrfInput.value : "";

  const fromSelect = document.getElementById("converter-from");
  const toSelect = document.getElementById("converter-to");
  const amountInput = document.getElementById("converter-amount");
  const swapButton = document.getElementById("converter-swap");
  const rateLine = document.getElementById("converter-rate-line");
  const rateError = document.getElementById("converter-rate-error");
  const amountError = document.getElementById("converter-amount-error");
  const convertError = document.getElementById("converter-convert-error");
  const resultValue = document.getElementById("converter-result-value");
  const convertButton = document.getElementById("converter-convert-btn");

  const VALIDATION = {
    empty: "Enter an amount to convert.",
    zeroOrNegative: "Amount must be greater than zero.",
  };

  let rateRequestId = 0;
  let convertRequestId = 0;

  function showError(el, message) {
    el.textContent = message;
    el.hidden = false;
  }

  function hideError(el) {
    el.hidden = true;
    el.textContent = "";
  }

  function syncUrl(from, to) {
    const params = new URLSearchParams(window.location.search);
    params.set("from", from);
    params.set("to", to);
    params.delete("amount");
    const query = params.toString();
    const nextUrl = query
      ? `${window.location.pathname}?${query}`
      : window.location.pathname;
    history.replaceState(null, "", nextUrl);
  }

  function clearResult() {
    resultValue.textContent = "—";
    resultValue.classList.add("converter-result-value--empty");
  }

  function setResult(amount, currency) {
    resultValue.textContent = `${Number(amount).toFixed(2)} ${currency}`;
    resultValue.classList.remove("converter-result-value--empty");
  }

  function setRateLoading(loading) {
    if (rateLine) {
      rateLine.classList.toggle("converter-rate--loading", loading);
    }
  }

  function setRateDisplay(from, to, rate) {
    hideError(rateError);
    if (!rateLine) return;
    rateLine.hidden = false;
    rateLine.textContent = `1 ${from} = ${rate} ${to}`;
  }

  function setRateUnavailable() {
    if (rateLine) {
      rateLine.hidden = true;
    }
    showError(
      rateError,
      "Couldn't fetch the exchange rate right now. Try again in a moment."
    );
  }

  function validateAmount() {
    hideError(amountError);
    const raw = amountInput.value.trim();
    if (raw === "") {
      showError(amountError, VALIDATION.empty);
      return null;
    }
    const amount = Number(raw);
    if (!Number.isFinite(amount)) {
      showError(amountError, "Enter a valid amount.");
      return null;
    }
    if (amount <= 0) {
      showError(amountError, VALIDATION.zeroOrNegative);
      return null;
    }
    return raw;
  }

  async function fetchRate(from, to) {
    const requestId = ++rateRequestId;
    setRateLoading(true);

    try {
      const params = new URLSearchParams({ from: from, to: to });
      const response = await fetch(`${rateUrl}?${params.toString()}`);
      const data = await response.json();

      if (requestId !== rateRequestId) return;

      if (!response.ok) {
        setRateUnavailable();
        return;
      }

      setRateDisplay(data.from, data.to, data.rate);
    } catch (_err) {
      if (requestId !== rateRequestId) return;
      setRateUnavailable();
    } finally {
      if (requestId === rateRequestId) {
        setRateLoading(false);
      }
    }
  }

  async function convert() {
    hideError(convertError);
    const amount = validateAmount();
    if (amount === null) return;

    const from = fromSelect.value;
    const to = toSelect.value;
    const requestId = ++convertRequestId;

    convertButton.disabled = true;
    convertButton.classList.add("btn--loading");

    try {
      const response = await fetch(convertUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken,
        },
        body: JSON.stringify({ from: from, to: to, amount: amount }),
      });
      const data = await response.json();

      if (requestId !== convertRequestId) return;

      if (!response.ok) {
        showError(
          convertError,
          data.error || "Couldn't convert right now. Try again in a moment."
        );
        return;
      }

      setRateDisplay(data.from, data.to, data.rate);
      setResult(data.converted_amount, data.to);
    } catch (_err) {
      if (requestId !== convertRequestId) return;
      showError(
        convertError,
        "Couldn't convert right now. Try again in a moment."
      );
    } finally {
      if (requestId === convertRequestId) {
        convertButton.disabled = false;
        convertButton.classList.remove("btn--loading");
      }
    }
  }

  function onPairChange(from, to, options) {
    fromSelect.value = from;
    toSelect.value = to;
    clearResult();
    hideError(convertError);
    hideError(amountError);
    syncUrl(from, to);

    if (options && options.animateSwap && swapButton) {
      swapButton.classList.remove("converter-swap--spin");
      void swapButton.offsetWidth;
      swapButton.classList.add("converter-swap--spin");
    }

    fetchRate(from, to);
  }

  fromSelect.addEventListener("change", function () {
    onPairChange(fromSelect.value, toSelect.value);
  });

  toSelect.addEventListener("change", function () {
    onPairChange(fromSelect.value, toSelect.value);
  });

  swapButton.addEventListener("click", function () {
    onPairChange(toSelect.value, fromSelect.value, { animateSwap: true });
  });

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    convert();
  });

  amountInput.addEventListener("keydown", function (event) {
    if (event.key === "Enter") {
      event.preventDefault();
      convert();
    }
  });
})();
