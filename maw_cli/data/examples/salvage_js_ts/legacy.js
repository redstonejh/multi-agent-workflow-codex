const state = { lastValue: null };

export function keepSystem(value) {
  state.lastValue = value;
  return duplicateFormat(value);
}

export function duplicateFormat(value) {
  return `value:${value}`;
}

export function duplicateFormatCopy(value) {
  return `value:${value}`;
}

export function deadLegacyPath(value) {
  return value * 13;
}
