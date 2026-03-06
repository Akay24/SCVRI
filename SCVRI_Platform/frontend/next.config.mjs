import path from "path";
import { fileURLToPath } from "url";

const __dirname = fileURLToPath(new URL(".", import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  experimental: {
    optimizePackageImports: ["recharts", "lucide-react"]
  },
  turbopack: {
    root: __dirname
  },
  allowedDevOrigins: [
    "192.168.29.211",
    "*.local",
  ]
};

export default nextConfig;
