import { sharedState } from "./state";
import { duplicateFormat } from "./duplicate";

export function keepSystem(value: number): string {
  sharedState.lastValue = value;
  return duplicateFormat(value);
}
