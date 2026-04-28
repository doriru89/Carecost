import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Signup from './Signup';

const navigateMock = vi.fn();
const signupMock = vi.fn();

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({
    signup: signupMock,
  }),
}));

describe('Signup', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    signupMock.mockResolvedValue(undefined);
  });

  it('routes first-time signup users to onboarding', async () => {
    render(
      <MemoryRouter>
        <Signup />
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'test@example.com' } });
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: 'password123' } });
    fireEvent.change(screen.getByLabelText(/confirm password/i), { target: { value: 'password123' } });
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: /get started/i }));

    await waitFor(() => {
      expect(signupMock).toHaveBeenCalledWith('test@example.com', 'password123');
      expect(navigateMock).toHaveBeenCalledWith('/onboarding');
    });
  });
});
