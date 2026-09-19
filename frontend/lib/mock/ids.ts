let seq = 0;

export function nextId(prefix: string): string {
  seq += 1;
  const stamp = Date.now().toString(36);
  return `${prefix}_${stamp}_${seq.toString(36)}`;
}

export function resetIdSeq(): void {
  seq = 0;
}
