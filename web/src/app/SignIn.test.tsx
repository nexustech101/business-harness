// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { api } from "../api/client";
import { apiError, json, serve } from "../test/api";
import { AuthProvider, useAuth } from "./auth";
import { SignIn } from "./SignIn";

const GOOD = "ak_good";
const me = { id: 2, name: "firm", prefix: "ak_good", is_admin: false, created_at: "2026-01-01T00:00:00Z" };

/** The API as far as sign-in goes: `/auth/me` knows one key; `revoked` makes every later request 401. */
function fakeApi() {
  const state = { revoked: false, keys: [] as (string | null)[] };
  serve((request) => {
    const key = request.headers.get("X-API-Key");
    state.keys.push(key);
    if (key !== GOOD || state.revoked) return apiError(401, "unauthorized", "Invalid or missing API key.");
    return json(200, { data: new URL(request.url).pathname === "/auth/me" ? me : { documents: 0 } });
  });
  return state;
}

function Gate() {
  const { me } = useAuth();
  if (!me) return <SignIn />;
  return (
    <p>
      Signed in as {me.name} <button onClick={() => void api.GET("/v1/workspace")}>Load workspace</button>
    </p>
  );
}

function renderApp() {
  const queryClient = new QueryClient();
  queryClient.setQueryData(["workspace"], { documents: 1 });
  render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider fallback={<p>Checking key</p>}>
        <Gate />
      </AuthProvider>
    </QueryClientProvider>,
  );
  return queryClient;
}

const signIn = async (key: string, remember = false) => {
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText("API key"), key);
  if (remember) await user.click(screen.getByRole("checkbox", { name: "Remember on this device" }));
  await user.click(screen.getByRole("button", { name: "Sign in" }));
  return user;
};

it("a refused key stays on the sign-in form with the reason and is not stored", async () => {
  const state = fakeApi();
  renderApp();
  await signIn("ak_wrong");
  await screen.findByText("This key is not valid, expired or revoked.");
  expect(screen.queryByText(/no longer valid/)).toBeNull(); // the 401 handler's notice is for ended sessions
  expect(state.keys).toEqual(["ak_wrong"]);
  expect(sessionStorage.length + localStorage.length).toBe(0);
});

it("signs in, sends the key, and a later 401 signs out with a notice", async () => {
  const state = fakeApi();
  const queryClient = renderApp();
  const user = await signIn(GOOD, true);
  await screen.findByText("Signed in as firm");
  expect(localStorage.getItem("tda.key")).toBe(GOOD);

  state.revoked = true;
  await user.click(screen.getByRole("button", { name: "Load workspace" }));
  await screen.findByText("Your key is no longer valid. Sign in again.");
  expect(state.keys).toEqual([GOOD, GOOD]);
  expect(localStorage.getItem("tda.key")).toBeNull();
  expect(queryClient.getQueryData(["stats"])).toBeUndefined(); // cache emptied
});

it("a stored key is checked before anything renders", async () => {
  const state = fakeApi();
  sessionStorage.setItem("tda.key", "ak_expired");
  renderApp();
  expect(screen.getByText("Checking key")).toBeTruthy();
  await screen.findByText("Your key is no longer valid. Sign in again.");
  expect(state.keys).toEqual(["ak_expired"]);
  await waitFor(() => expect(sessionStorage.getItem("tda.key")).toBeNull());

  cleanup();
  sessionStorage.setItem("tda.key", GOOD);
  renderApp();
  await screen.findByText("Signed in as firm");
});
