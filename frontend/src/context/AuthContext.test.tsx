import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, act, waitFor } from '@testing-library/react';
import React from 'react';
import { AuthProvider, useAuth } from './AuthContext';

const FAKE_TOKEN =
  'eyJhbGciOiJIUzI1NiJ9.' +
  btoa(JSON.stringify({ sub: 'u1', email: 'test@test.com', iss: 'carecost', iat: 1, exp: 9999999999 })) +
  '.sig';

const COMPLETE_USER_PROFILE = {
  fullName: 'Test User',
  dob: '2000-01-01',
  zip: '02101',
  phone: '555-0100',
  onboarding_completed: true,
};

const COMPLETE_INSURANCE = {
  carrier: 'BCBS',
  planName: 'HMO Blue',
  planType: 'PPO',
  deductible: 500,
  oopMax: 3000,
  coinsurance: 20,
};

vi.mock('@/api/client', async () => {
  const actual = await vi.importActual<typeof import('@/api/client')>('@/api/client');
  return {
    ...actual,
    fetchUserMe: vi.fn(),
    patchUserMe: vi.fn().mockResolvedValue({}),
    setApiAccessTokenGetter: vi.fn(),
  };
});

vi.mock('@/lib/giContinuity', () => ({
  clearAllGiContinuityForLogout: vi.fn(),
}));

import { fetchUserMe, patchUserMe } from '@/api/client';

let captured: ReturnType<typeof useAuth> | null = null;

function Probe() {
  captured = useAuth();
  return null;
}

function renderWithAuth() {
  return render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  );
}

describe('AuthContext onboardingComplete restoration', () => {
  beforeEach(() => {
    captured = null;
    sessionStorage.clear();
    vi.clearAllMocks();
  });

  afterEach(() => {
    sessionStorage.clear();
  });

  it('restores onboardingComplete when API profile has onboarding_completed: true', async () => {
    sessionStorage.setItem('carecost_token', FAKE_TOKEN);
    vi.mocked(fetchUserMe).mockResolvedValue({
      sub: 'u1',
      email: 'test@test.com',
      user_profile: COMPLETE_USER_PROFILE,
      insurance_profile: COMPLETE_INSURANCE,
    });

    renderWithAuth();

    await waitFor(() => {
      expect(captured!.meReady).toBe(true);
    });

    expect(captured!.onboardingComplete).toBe(true);
    expect(captured!.profile?.onboardingCompleted).toBe(true);
  });

  it('auto-derives onboardingComplete when profile is complete but flag missing', async () => {
    sessionStorage.setItem('carecost_token', FAKE_TOKEN);
    const profileNoFlag = { ...COMPLETE_USER_PROFILE };
    delete (profileNoFlag as Record<string, unknown>).onboarding_completed;

    vi.mocked(fetchUserMe).mockResolvedValue({
      sub: 'u1',
      email: 'test@test.com',
      user_profile: profileNoFlag,
      insurance_profile: COMPLETE_INSURANCE,
    });

    renderWithAuth();

    await waitFor(() => {
      expect(captured!.meReady).toBe(true);
    });

    expect(captured!.onboardingComplete).toBe(true);
  });

  it('keeps onboardingComplete false when profile is incomplete', async () => {
    sessionStorage.setItem('carecost_token', FAKE_TOKEN);
    vi.mocked(fetchUserMe).mockResolvedValue({
      sub: 'u1',
      email: 'test@test.com',
      user_profile: null,
      insurance_profile: null,
    });

    renderWithAuth();

    await waitFor(() => {
      expect(captured!.meReady).toBe(true);
    });

    expect(captured!.onboardingComplete).toBe(false);
  });

  it('completeOnboarding() sets flag in-session', async () => {
    sessionStorage.setItem('carecost_token', FAKE_TOKEN);
    vi.mocked(fetchUserMe).mockResolvedValue({
      sub: 'u1',
      email: 'test@test.com',
      user_profile: null,
      insurance_profile: null,
    });

    renderWithAuth();

    await waitFor(() => {
      expect(captured!.meReady).toBe(true);
    });

    expect(captured!.onboardingComplete).toBe(false);

    act(() => {
      captured!.completeOnboarding();
    });

    expect(captured!.onboardingComplete).toBe(true);
  });
});
