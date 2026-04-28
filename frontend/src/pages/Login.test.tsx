import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Login from './Login';

const navigateMock = vi.fn();
const loginMock = vi.fn();

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({
    login: loginMock,
  }),
}));

describe('Login', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    loginMock.mockResolvedValue(undefined);
  });

  it('navigates to map with symptom prompt flag on successful login', async () => {
    render(
      <MemoryRouter>
        <Login />
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'test@example.com' } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'password123' } });
    fireEvent.click(screen.getByRole('button', { name: /log in/i }));

    await waitFor(() => {
      expect(loginMock).toHaveBeenCalledWith('test@example.com', 'password123');
      expect(navigateMock).toHaveBeenCalledWith('/map', { state: { openSymptoms: true } });
    });
  });
});
