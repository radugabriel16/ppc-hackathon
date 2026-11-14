import { Navigate, Outlet } from "react-router-dom";
import { useSession } from "../data/hooks";
import { ErrorNotice, Loading } from "./common";

export function Authenticated() {
  const session = useSession();
  if (session.isPending) return <Loading />;
  if (session.error)
    return (
      <ErrorNotice error={session.error} retry={() => void session.refetch()} />
    );
  return session.data ? <Outlet /> : <Navigate to="/login" replace />;
}
