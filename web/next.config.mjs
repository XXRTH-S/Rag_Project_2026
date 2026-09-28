/** @type {import('next').NextConfig} */
const nextConfig = {
  devIndicators: false,
  output: process.env.VERCEL ? undefined : "standalone",
  reactStrictMode: true,
  // หาก backend URL ไม่ถูกต้อง ให้ข้าม proxy และบันทึก error เพื่อให้หน้าเว็บยังเปิดได้
  async rewrites() {
    const origin = process.env.BACKEND_HTTPS_ORIGIN;
    if (!origin) return [];

    let url;
    try {
      url = new URL(origin);
    } catch {
      console.error(
        `BACKEND_HTTPS_ORIGIN ไม่ใช่ URL ที่ถูกต้อง: ${JSON.stringify(origin)} — ` +
          `ต้องเป็นรูปแบบ https://host เท่านั้น · ข้ามการ proxy ไปยัง API`,
      );
      return [];
    }

    const problem =
      url.protocol !== "https:"
        ? "ต้องเป็น https"
        : url.username || url.password
          ? "ต้องไม่มีชื่อผู้ใช้หรือรหัสผ่าน"
          : url.search || url.hash
            ? "ต้องไม่มี query หรือ hash"
            : url.pathname !== "/"
              ? "ต้องไม่มี path ต่อท้าย"
              : null;

    if (problem) {
      console.error(
        `BACKEND_HTTPS_ORIGIN ใช้ไม่ได้ (${problem}): ${origin} — ข้ามการ proxy ไปยัง API`,
      );
      return [];
    }

    return [
      { source: "/api/:path*", destination: `${url.origin}/api/:path*` },
      { source: "/health", destination: `${url.origin}/health` },
      { source: "/health/:path*", destination: `${url.origin}/health/:path*` },
    ];
  },
};

export default nextConfig;
