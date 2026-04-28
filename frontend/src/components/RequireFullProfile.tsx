import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '@/context/AuthContext';
import { isInsuranceProfileComplete, isUserProfileComplete } from '@/lib/profileComplete';
import CareCostLogo from '@/components/CareCostLogo';

/** Map / saved require auth + saved profile + coverage + completed onboarding wizard. */
export default function RequireFullProfile({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, profile, insurance, meReady, onboardingComplete } = useAuth();
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

  const userOk = isUserProfileComplete(profile);
  const insOk = isInsuranceProfileComplete(insurance);

  if (!userOk || !insOk || !onboardingComplete) {
    return <Navigate to="/onboarding" replace />;
  }

  return <>{children}</>;
}
