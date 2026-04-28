import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import CrtSelectionDialog from './CrtSelectionDialog';

describe('CrtSelectionDialog', () => {
  it('lets users close the dialog via the close button', () => {
    const onOpenChange = vi.fn();

    render(
      <CrtSelectionDialog
        open
        onOpenChange={onOpenChange}
        onSelect={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /close/i }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
