export type DemoAuthState = "loading" | "signed-in" | "signed-out";

type Session = { user: unknown } | null;

type Auth = {
  getSession: () => Promise<{ data: { session: Session } }>;
  onAuthStateChange: (
    callback: (event: string, session: Session) => void,
  ) => { data: { subscription: { unsubscribe: () => void } } };
};

export function watchDemoAuthState(auth: Auth, onChange: (state: DemoAuthState) => void) {
  let active = true;
  let authEventReceived = false;
  onChange("loading");

  const { data: { subscription } } = auth.onAuthStateChange((_event, session) => {
    if (!active) return;
    authEventReceived = true;
    onChange(session?.user ? "signed-in" : "signed-out");
  });

  void auth.getSession().then(
    ({ data }) => {
      if (active && !authEventReceived)
        onChange(data.session?.user ? "signed-in" : "signed-out");
    },
    () => {
      if (active && !authEventReceived) onChange("signed-out");
    },
  );

  return () => {
    active = false;
    subscription.unsubscribe();
  };
}
