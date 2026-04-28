import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { render, screen } from '@testing-library/react';
import RequireAuth from './RequireAuth';

const useAuthMock = vi.fn();

vi.mock('@/context/AuthContext', () => ({
  useAuth: () => useAuthMock(),
}));

function renderProtected(initialPath = '/map') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route
          path="/map"
          element={
            <RequireAuth>
              <div>protected page</div>
            </RequireAuth>
          }
        />
        <Route path="/login" element={<div>login page</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('RequireAuth', () => {
  beforeEach(() => {
    useAuthMock.mockReset();
  });

  it('redirects to login when unauthenticated', () => {
    useAuthMock.mockReturnValue({ isAuthenticated: false, meReady: false });
    renderProtected();
    expect(screen.getByText('login page')).toBeInTheDocument();
  });

  it('shows loading state while profile is loading', () => {
    useAuthMock.mockReturnValue({ isAuthenticated: true, meReady: false });
    renderProtected();
    expect(screen.getByText(/Loading your profile/i)).toBeInTheDocument();
  });

  it('renders protected content when authenticated and ready', () => {
    useAuthMock.mockReturnValue({ isAuthenticated: true, meReady: true });
    renderProtected();
    expect(screen.getByText('protected page')).toBeInTheDocument();
  });
});
