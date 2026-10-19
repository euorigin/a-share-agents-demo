/** @type {import('next').NextConfig} */
const nextConfig = {
  devIndicators: false,
  // Proxy /chat requests to the backend server
  async rewrites() {
    return [
      {
        source: "/chat",
        destination: "http://127.0.0.1:8000/chat",
      },
      {
        source: "/chat/:path*",
        destination: "http://127.0.0.1:8000/chat/:path*",
      },
      {
        source: "/chatkit",
        destination: "http://127.0.0.1:8000/chatkit",
      },
      {
        source: "/chatkit/:path*",
        destination: "http://127.0.0.1:8000/chatkit/:path*",
      },
      {
        // 走势图数据（K线 / 分时）
        source: "/stock/:path*",
        destination: "http://127.0.0.1:8000/stock/:path*",
      },
    ];
  },
};

export default nextConfig;
