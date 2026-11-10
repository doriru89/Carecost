import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import ScrollToTop from "@/components/layout/ScrollToTop";
import { Toaster as Sonner } from "./components/ui/sonner";
import { Toaster } from "./components/ui/toaster";
import { TooltipProvider } from "./components/ui/tooltip";
import Index from "./pages/Index";
import NotFound from "./pages/NotFound";
import WhyItMatters from "./pages/WhyItMatters";
import Team from "./pages/Team";
import OurData from "./pages/OurData";
import ProductVision from "./pages/ProductVision";
import CareApp from "./app/pages/CareApp";

const queryClient = new QueryClient();

/** No accounts (D19): the price tool at /start is open to everyone. */
const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <Sonner />
      <BrowserRouter basename={import.meta.env.BASE_URL.replace(/\/$/, "")}>
        <ScrollToTop />
        <Routes>
          <Route path="/" element={<Index />} />
          <Route path="/start" element={<CareApp />} />
          <Route path="/why-it-matters" element={<WhyItMatters />} />
          <Route path="/team" element={<Team />} />
          <Route path="/our-data" element={<OurData />} />
          <Route path="/our-approach" element={<ProductVision />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
