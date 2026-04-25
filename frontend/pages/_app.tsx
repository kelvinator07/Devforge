import { ClerkProvider } from "@clerk/nextjs";
import type { AppProps } from "next/app";
import { Toaster } from "react-hot-toast";
import "../styles/globals.css";

export default function MyApp({ Component, pageProps }: AppProps) {
  return (
    <ClerkProvider {...pageProps}>
      <Component {...pageProps} />
      <Toaster
        position="bottom-right"
        toastOptions={{
          style: {
            background: "#18181b",
            color: "#e4e4e7",
            border: "1px solid #3f3f46",
            fontSize: "13px",
          },
          success: { iconTheme: { primary: "#10b981", secondary: "#18181b" } },
          error: { iconTheme: { primary: "#f43f5e", secondary: "#18181b" } },
        }}
      />
    </ClerkProvider>
  );
}
