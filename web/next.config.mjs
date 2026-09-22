/** @type {import('next').NextConfig} */
const nextConfig = {
  devIndicators: false,
  output: process.env.VERCEL ? undefined : "standalone",
  reactStrictMode: true,
  async rewrites() {
    const origin = process.env.BACKEND_HTTPS_ORIGIN;
    if (!origin) return [];
    const url = new URL(origin);
    if (url.protocol !== "https:" || url.username || url.password || url.search || url.hash || url.pathname !== "/") {
      throw new Error("BACKEND_HTTPS_ORIGIN must be an HTTPS origin without a path or credentials");
    }
    return [{ source: "/api/:path*", destination: `${url.origin}/api/:path*` }, { source: "/health/:path*", destination: `${url.origin}/health/:path*` }];
  },
};

export default nextConfig;
