import { useState } from 'react';
import Navbar from '@/components/layout/Navbar';
import Footer from '@/components/layout/Footer';
import ProviderCard from '@/components/providers/ProviderCard';
import { Bookmark } from 'lucide-react';
import type { Provider, CostEstimate } from '@/types';

// Placeholder until a saved-providers API exists.
const MOCK_SAVED: { provider: Provider; estimate: CostEstimate }[] = [
  {
    provider: { id: '1', name: 'Boston Medical Center', specialty: ['Primary Care'], address: '1 Boston Medical Center Pl, Boston, MA', lat: 42.3346, lng: -71.0721, phone: '(617) 638-8000', inNetwork: true, distance: 1.2 },
    estimate: { providerId: '1', procedureName: 'Office Visit (New Patient)', patientResponsibility: 80, copay: 30, deductibleApplied: 50 },
  },
  {
    provider: { id: '5', name: 'Tufts Medical Center', specialty: ['Urgent Care', 'Primary Care'], address: '800 Washington St, Boston, MA', lat: 42.3492, lng: -71.0637, phone: '(617) 636-5000', inNetwork: true, distance: 1.8 },
    estimate: { providerId: '5', procedureName: 'Urgent Care Visit', patientResponsibility: 35, copay: 35 },
  },
];

const Saved = () => {
  const [items] = useState(MOCK_SAVED);

  return (
    <div className="min-h-screen flex flex-col">
      <Navbar />
      <div className="flex-1 container mx-auto px-4 py-10 max-w-2xl animate-fade-in">
        <h1 className="text-2xl font-bold mb-6">Saved providers</h1>
        {items.length === 0 ? (
          <div className="text-center py-16">
            <Bookmark className="w-12 h-12 text-muted-foreground mx-auto mb-3" />
            <p className="font-medium">No saved providers yet</p>
            <p className="text-sm text-muted-foreground mt-1">Save providers from the map to see them here.</p>
          </div>
        ) : (
          <div className="space-y-4">
            {items.map(({ provider, estimate }) => (
              <ProviderCard key={provider.id} provider={provider} estimate={estimate} saved />
            ))}
          </div>
        )}
      </div>
      <Footer />
    </div>
  );
};

export default Saved;
