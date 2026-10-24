/** @type {import('next').NextConfig} */
const assetPrefix = process.env.PASARPULSE_ASSET_PREFIX || "";

const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  assetPrefix,
  async rewrites() {
    const backend = process.env.PASARPULSE_INTERNAL_API_URL || "http://backend:8000";
    return [{ source: "/api/:path*", destination: `${backend}/:path*` }];
  },
};

export default nextConfig;
