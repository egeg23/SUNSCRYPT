import { Golos_Text, JetBrains_Mono, Unbounded } from "next/font/google";

// Display: Unbounded (wordmark, headings). Body: Golos Text. Figures: JetBrains Mono. All with Cyrillic.
export const display = Unbounded({ subsets: ["latin", "cyrillic"], weight: ["500", "700"], variable: "--font-display" });
export const body = Golos_Text({ subsets: ["latin", "cyrillic"], weight: ["400", "500", "600"], variable: "--font-body" });
export const mono = JetBrains_Mono({ subsets: ["latin", "cyrillic"], weight: ["400", "500"], variable: "--font-mono" });
