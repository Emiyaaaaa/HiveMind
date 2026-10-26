/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    // Demo mode serves `/api/v1/*` from App Router mock handlers.
    if (
      process.env.AGENTFLOW_MOCK === "1" ||
      process.env.AGENTFLOW_MOCK === "true"
    ) {
      return [];
    }
    const backend = process.env.AGENTFLOW_API_URL || "http://localhost:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${backend}/:path*`,
      },
    ];
  },
};

export default nextConfig;
