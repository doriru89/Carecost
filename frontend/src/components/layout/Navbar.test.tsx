import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Navbar from './Navbar';

const useAuthMock = vi.fn();
const navigateMock = vi.fn();

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

vi.mock('@/context/AuthContext', () => ({
  useAuth: () => useAuthMock(),
}));

describe('Navbar', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows Profile navigation when authenticated', () => {
    useAuthMock.mockReturnValue({
      isAuthenticated: true,
      profile: { fullName: 'Test User' },
      user: { email: 'test@example.com' },
      logout: vi.fn(),
    });

    render(
      <MemoryRouter>
        <Navbar />
      </MemoryRouter>,
    );

    expect(screen.getAllByRole('link', { name: /profile/i }).length).toBeGreaterThan(0);
  });

  it('hides Profile navigation when logged out', () => {
    useAuthMock.mockReturnValue({
      isAuthenticated: false,
      profile: null,
      user: null,
      logout: vi.fn(),
    });

    render(
      <MemoryRouter>
        <Navbar />
      </MemoryRouter>,
    );

    expect(screen.queryByRole('link', { name: /profile/i })).not.toBeInTheDocument();
  });
});
