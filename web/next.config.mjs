/** @type {import('next').NextConfig} */
const nextConfig = {
  webpack: (config, { dev }) => {
    if (dev) {
      config.cache = false;
    }
    config.module.rules.push({ 
        test: /\.svg$/,
        use: ['@svgr/webpack'], 
        }); 
    return config;
  },
};

export default nextConfig;
