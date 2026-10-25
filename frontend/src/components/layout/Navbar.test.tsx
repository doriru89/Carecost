import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Navbar from './Navbar';

describe('Navbar', () => {
  it('links to the price tool and has no account links (D19)', () => {
    render(
      <MemoryRouter>
        <Navbar />
      </MemoryRouter>,
    );
    const start = screen.getAllByRole('link', { name: /get started/i });
    expect(start[0].getAttribute('href')).toBe('/start');
    expect(screen.queryByRole('link', { name: /log in|sign up|profile|settings/i })).toBeNull();
  });
});
