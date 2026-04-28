import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Onboarding from './Onboarding';

const navigateMock = vi.fn();

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

vi.mock('@/api/client', async () => {
  const actual = await vi.importActual<typeof import('@/api/client')>('@/api/client');
  return {
    ...actual,
    fetchInsuranceOptions: vi.fn().mockImplementation(() => new Promise(() => {})),
    patchUserMe: vi.fn(),
    postIntake: vi.fn(),
  };
});

vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({
    setProfile: vi.fn(),
    setInsurance: vi.fn(),
    setIntakePayload: vi.fn(),
    completeOnboarding: vi.fn(),
    meReady: true,
    isAuthenticated: true,
    profile: null,
    insurance: null,
    onboardingComplete: false,
  }),
}));

describe('Onboarding', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('provides a skip action to continue directly to map', () => {
    render(
      <MemoryRouter>
        <Onboarding />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole('button', { name: /skip for now/i }));
    expect(navigateMock).toHaveBeenCalledWith('/map');
  });
});
