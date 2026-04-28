import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '@/context/AuthContext';
import CareCostLogo from '@/components/CareCostLogo';

export default function RequireAuth({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, meReady } = useAuth();
  const location = useLocation();

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  if (!meReady) {
    return (
      <div className="flex min-h-dvh flex-col items-center justify-center gap-4 p-6">
        <CareCostLogo showTagline={false} compact />
        <p className="text-sm text-muted-foreground">Loading your profile…</p>
      </div>
    );
  }

  return <>{children}</>;
}
