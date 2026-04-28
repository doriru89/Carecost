import { Heart } from 'lucide-react';

const CareCostLogo = ({ showTagline = false, compact = false }: { showTagline?: boolean; compact?: boolean }) => {
  return (
    <div className="flex flex-col">
      <span className={`font-bold tracking-tight ${compact ? 'text-xl' : 'text-2xl'}`}>
        CareC
        <Heart className="inline-block fill-primary stroke-primary" style={{ width: compact ? '0.75em' : '0.85em', height: compact ? '0.75em' : '0.85em', verticalAlign: 'baseline', marginBottom: '0.05em' }} />
        st
      </span>
      {showTagline && (
        <span className="text-xs text-muted-foreground mt-0.5">
          Know what care costs before it costs you.
        </span>
      )}
    </div>
  );
};

export default CareCostLogo;
