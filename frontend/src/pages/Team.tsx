import { useState } from 'react';
import Navbar from '@/components/layout/Navbar';
import Footer from '@/components/layout/Footer';

/**
 * Headshots: add JPG or PNG files under frontend/public/team/ using these filenames
 * (paths below). They are served at /team/<filename> from the site root.
 */
const TEAM = [
  {
    photo: '/team/kenza-moussaoui.png',
    initials: 'KM',
    name: 'Kenza Moussaoui Rahali, M.D.',
    school: 'Yale School of Management',
    origin: 'Morocco',
    bio: `I am a physician, and my training has shaped how I see care: every patient deserves clarity, dignity, and a fair shot at getting help without financial ruin. I am at Yale SOM because I want to bridge clinical reality with better systems. My mission is to advance health equity, strengthen patient care, and push for a healthcare system that is genuinely equitable. I bring that commitment to this team every day.`,
  },
  {
    photo: '/team/Austin-Zheng.png',
    initials: 'AZ',
    name: 'Austin Zheng',
    school: 'Yale School of Management',
    origin: 'China',
    bio: `I come from China and studied at Yale SOM. Product management is how I turn ambiguity into something people can actually use. I am putting that craft toward a simple goal: work on products that matter, that improve real lives, and that leave the world a little better than we found it. This project is exactly that kind of bet.`,
  },
  {
    photo: '/team/davis-schmidt.jpeg',
    initials: 'DS',
    name: 'David Schmidt',
    school: 'Yale School of Management',
    origin: 'Germany',
    bio: `I am from Germany and studied at Yale SOM. My years in consulting taught me how to pressure-test ideas against reality. I am here to make sure our product solves real problems, not slide-deck problems, and that it reaches the people who need it most. Strategy only counts if it shows up where patients live.`,
  },
] as const;

function TeamMemberCard({
  photo,
  initials,
  name,
  school,
  origin,
  bio,
}: (typeof TEAM)[number]) {
  const [imgFailed, setImgFailed] = useState(false);

  return (
    <article className="rounded-2xl border border-border bg-card p-6 md:p-8 shadow-card flex flex-col items-center text-center md:items-start md:text-left">
      <div className="mb-6 w-full max-w-[220px] mx-auto md:mx-0">
        <div className="relative aspect-square w-full overflow-hidden rounded-2xl border border-border bg-muted">
          {!imgFailed ? (
            <img
              src={photo}
              alt={name}
              className="h-full w-full object-cover"
              onError={() => setImgFailed(true)}
            />
          ) : (
            <div className="flex h-full w-full items-center justify-center bg-primary/15">
              <span className="text-4xl font-bold tracking-tight text-primary/80">{initials}</span>
            </div>
          )}
        </div>
      </div>
      <h2 className="text-lg font-bold text-foreground mb-1">{name}</h2>
      <p className="text-sm text-primary font-medium mb-1">{school}</p>
      <p className="text-xs text-muted-foreground uppercase tracking-wide mb-4">{origin}</p>
      <p className="text-sm text-muted-foreground leading-relaxed">{bio}</p>
    </article>
  );
}

const Team = () => (
  <div className="min-h-screen flex flex-col">
    <Navbar />

    <main className="flex-1">
      <section className="container mx-auto px-4 py-10 sm:py-12 md:py-16 max-w-5xl pb-[max(2rem,env(safe-area-inset-bottom))]">
        <p className="text-xs font-semibold uppercase tracking-wider text-primary mb-3 text-center">Team</p>
        <h1 className="text-2xl md:text-3xl font-bold text-center mb-8 max-w-3xl mx-auto leading-tight">
          Three continents, one mission
        </h1>
        <p className="text-center text-muted-foreground leading-relaxed max-w-2xl mx-auto mb-14 md:mb-16">
          We bring together medicine, product, and strategy: clinical insight, product
          judgment, and consulting rigor. From Morocco, China, and Germany, we are combining what we
          have learned across healthcare and technology because we believe transparent, personalized cost information can
          change who gets care and who gets blindsided. This project is our bet on that impact.
        </p>

        <div className="grid gap-10 md:gap-12 md:grid-cols-2">
          {TEAM.map((m, i) => (
            <div key={m.name} className={i === TEAM.length - 1 ? 'md:col-span-2 md:max-w-md md:mx-auto' : ''}>
              <TeamMemberCard {...m} />
            </div>
          ))}
        </div>
      </section>
    </main>

    <Footer />
  </div>
);

export default Team;
