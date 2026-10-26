/** Demo mode: serve in-memory API so the console runs without Java/Python backends. */
export function isMockEnabled(): boolean {
  return (
    process.env.AGENTFLOW_MOCK === "1" ||
    process.env.AGENTFLOW_MOCK === "true"
  );
}
