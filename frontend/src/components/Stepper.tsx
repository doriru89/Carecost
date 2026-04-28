import { Check } from 'lucide-react';

interface StepperProps {
  steps: string[];
  currentStep: number;
}

const Stepper = ({ steps, currentStep }: StepperProps) => (
  <div className="flex items-center justify-center gap-2 mb-8">
    {steps.map((label, i) => (
      <div key={label} className="flex items-center gap-2">
        <div className={`flex items-center justify-center w-9 h-9 rounded-full text-sm font-semibold transition-colors ${
          i < currentStep
            ? 'bg-primary text-primary-foreground'
            : i === currentStep
              ? 'bg-primary text-primary-foreground ring-4 ring-primary/20'
              : 'bg-muted text-muted-foreground'
        }`}>
          {i < currentStep ? <Check className="w-4 h-4" /> : i + 1}
        </div>
        <span className={`text-sm hidden sm:inline ${i === currentStep ? 'font-medium text-foreground' : 'text-muted-foreground'}`}>
          {label}
        </span>
        {i < steps.length - 1 && <div className={`w-8 h-0.5 ${i < currentStep ? 'bg-primary' : 'bg-border'}`} />}
      </div>
    ))}
  </div>
);

export default Stepper;
