import { ClerkProvider } from "@clerk/nextjs";
import type { AppProps } from "next/app";
import { Inter } from "next/font/google";
import { Toaster } from "react-hot-toast";
import "../styles/globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

export default function MyApp({ Component, pageProps }: AppProps) {
  return (
    <ClerkProvider {...pageProps}>
      <div className={`${inter.variable}`}>
        <Component {...pageProps} />
      </div>
      <Toaster
        position="bottom-right"
        toastOptions={{
          duration: 3500,
          style: {
            background: "#11141a",
            color: "#e8eaed",
            border: "1px solid #2c323b",
            fontSize: "13px",
            padding: "10px 14px",
            boxShadow: "0 4px 12px rgba(0,0,0,0.5)",
          },
          success: { iconTheme: { primary: "#10b981", secondary: "#11141a" } },
          error: { iconTheme: { primary: "#f43f5e", secondary: "#11141a" } },
        }}
      />
    </ClerkProvider>
  );
}
