/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "img1.hscicdn.com" },
      { protocol: "https", hostname: "cricbuzz-cricket.p.rapidapi.com" },
    ],
  },
};

export default nextConfig;
