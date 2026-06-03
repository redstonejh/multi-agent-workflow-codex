export async function loadProfile() {
  const response = await fetch("/api/profile");
  const data = await response.json();
  document.querySelector("#app")!.textContent = data.displayName;
}

export function duplicateLabel(value: string) {
  return value.trim().toUpperCase();
}

export function duplicateLabelOld(value: string) {
  return value.trim().toUpperCase();
}
