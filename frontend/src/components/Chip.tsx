interface ChipProps {
  label: string;
  active?: boolean;
  onClick?: () => void;
}

const Chip = ({ label, active = false, onClick }: ChipProps) => (
  <button
    type="button"
    onClick={onClick}
    className={`px-4 py-2 rounded-full text-sm font-medium transition-colors border ${
      active
        ? 'bg-primary text-primary-foreground border-primary'
        : 'bg-card text-foreground border-border hover:border-primary/50'
    }`}
  >
    {label}
  </button>
);

export default Chip;
