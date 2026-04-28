import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '@/context/AuthContext';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Checkbox } from '@/components/ui/checkbox';
import CareCostLogo from '@/components/CareCostLogo';

const Signup = () => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [terms, setTerms] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const { signup } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (password !== confirm) return;
    if (!terms) return;
    setError('');
    setLoading(true);
    try {
      await signup(email, password);
      navigate('/onboarding');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Signup failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex">
      <div className="hidden lg:flex lg:w-1/2 bg-gradient-to-br from-primary/20 via-primary/10 to-background items-center justify-center p-12">
        <div className="text-center">
          <CareCostLogo showTagline />
          <p className="mt-6 text-muted-foreground max-w-sm mx-auto">
            Join thousands of patients taking control of their healthcare spending.
          </p>
        </div>
      </div>

      <div className="flex-1 flex items-center justify-center p-6">
        <div className="w-full max-w-sm animate-fade-in">
          <div className="lg:hidden mb-8">
            <CareCostLogo showTagline />
          </div>
          <h1 className="text-2xl font-bold mb-1">Create your account</h1>
          <p className="text-muted-foreground mb-8 text-sm">Start seeing personalized cost estimates</p>

          {error && (
            <div className="mb-4 p-3 rounded-md bg-destructive/10 text-destructive text-sm">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <Label htmlFor="email">Email</Label>
              <Input id="email" type="email" value={email} onChange={e => setEmail(e.target.value)} required className="mt-1" />
            </div>
            <div>
              <Label htmlFor="password">Password</Label>
              <Input id="password" type="password" value={password} onChange={e => setPassword(e.target.value)} required minLength={6} className="mt-1" />
            </div>
            <div>
              <Label htmlFor="confirm">Confirm password</Label>
              <Input id="confirm" type="password" value={confirm} onChange={e => setConfirm(e.target.value)} required className="mt-1" />
              {confirm && password !== confirm && <p className="text-xs text-destructive mt-1">Passwords don&apos;t match</p>}
            </div>
            <div className="flex items-start gap-2">
              <Checkbox id="terms" checked={terms} onCheckedChange={v => setTerms(v === true)} className="mt-0.5" />
              <Label htmlFor="terms" className="text-sm text-muted-foreground leading-snug">
                I agree to the <a href="#" className="text-primary hover:underline">Terms</a> and <a href="#" className="text-primary hover:underline">Privacy Policy</a>
              </Label>
            </div>
            <Button type="submit" className="w-full bg-primary text-primary-foreground hover:bg-primary-hover h-11" disabled={loading || !terms}>
              {loading ? 'Creating account…' : 'Get started'}
            </Button>
          </form>

          <p className="text-sm text-muted-foreground text-center mt-6">
            Already have an account?{' '}
            <Link to="/login" className="text-primary font-medium hover:underline">
              Log in
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
};

export default Signup;
