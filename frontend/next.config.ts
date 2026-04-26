import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Pages Router (default in Next 16 when no /app dir).
  reactStrictMode: true,
  // Static export → deploys cleanly to S3 + CloudFront (terraform/8_frontend).
  // Required: no /api routes, no getServerSideProps, no middleware. After #B2
  // the admin token lives only on the FastAPI backend, so we don't need any
  // server runtime in the frontend.
  output: "export",
  // Next's image optimizer requires a server runtime; static export needs raw images.
  images: { unoptimized: true },
};

export default nextConfig;
