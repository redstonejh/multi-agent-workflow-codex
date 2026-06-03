window.sharedState = { saved: false };

function keepButton() {
  document.getElementById("keep-button").addEventListener("click", () => {
    window.sharedState.saved = true;
  });
}

function duplicateMessage(value) {
  return value.trim().toLowerCase();
}

function duplicateMessageOld(value) {
  return value.trim().toLowerCase();
}

keepButton();
