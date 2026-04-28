import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';

/** Scrolls window to top on client-side navigation so a long previous page does not keep scroll position. */
export default function ScrollToTop() {
  const { pathname } = useLocation();

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);

  return null;
}
