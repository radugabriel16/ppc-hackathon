import { useState } from "react";
import { Navigate } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Chip,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { ArrowForward, Bolt, CheckCircleOutline } from "@mui/icons-material";
import { useDataMode, useLogin, useSession } from "../data/hooks";
import type { Role } from "../data/models";
import { ErrorNotice, Loading } from "../components/common";

export function Login() {
  const session = useSession();
  const login = useLogin();
  const mode = useDataMode();
  const demo = mode === "demo";
  const [name, setName] = useState(demo ? "Alex Morgan" : "");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("OPERATOR");
  if (session.isPending) return <Loading />;
  if (session.data) return <Navigate to="/map" replace />;
  return (
    <Box
      sx={{
        minHeight: "100vh",
        display: "grid",
        gridTemplateColumns: { xs: "1fr", md: "1.1fr 1fr" },
      }}
    >
      <Stack
        sx={{
          bgcolor: "primary.dark",
          color: "white",
          p: { xs: 4, lg: 9 },
          justifyContent: "space-between",
          minHeight: { md: "100vh" },
          backgroundImage:
            "radial-gradient(ellipse at 100% 0%, #345b3c 0%, transparent 55%)",
        }}
      >
        <Stack direction="row" gap={1} alignItems="center">
          <Box className="brand-mark">
            <Bolt />
          </Box>
          <Typography variant="h5">FileGrid.</Typography>
        </Stack>
        <Box sx={{ my: 8, maxWidth: 480 }}>
          <Chip
            label="NETWORK OPERATIONS, CONNECTED"
            sx={{ bgcolor: "#29493a", color: "#c5e56b", mb: 3 }}
          />
          <Typography
            sx={{
              fontSize: { xs: 40, lg: 56 },
              fontWeight: 550,
              lineHeight: 1.08,
              letterSpacing: "-2px",
            }}
          >
            Every file.
            <br />
            Every asset.
            <br />
            <span style={{ color: "#c5e56b" }}>A clearer picture.</span>
          </Typography>
          <Typography sx={{ color: "#a4b8ac", mt: 3, lineHeight: 1.8 }}>
            Your electricity network, evidence, and decisions in one connected
            workspace.
          </Typography>
          <Stack spacing={1.8} mt={5}>
            {[
              "Inspect your network in context",
              "Ingest large files with confidence",
              "Turn evidence into action",
            ].map((text) => (
              <Stack direction="row" spacing={1.2} key={text}>
                <CheckCircleOutline sx={{ color: "#c5e56b", fontSize: 19 }} />
                <Typography variant="body2">{text}</Typography>
              </Stack>
            ))}
          </Stack>
        </Box>
        <Typography variant="caption" color="#8aa096">
          Built for the people who keep Romania connected.
        </Typography>
      </Stack>
      <Stack justifyContent="center" alignItems="center" sx={{ p: 3 }}>
        <Paper
          component="form"
          variant="outlined"
          onSubmit={(e) => {
            e.preventDefault();
            login.mutate({ name, role, password: demo ? undefined : password });
          }}
          sx={{ p: { xs: 3, sm: 5 }, width: "100%", maxWidth: 450 }}
        >
          <Typography className="eyebrow">WELCOME TO FILEGRID</Typography>
          <Typography variant="h4" mt={1} mb={1}>
            Your grid starts here.
          </Typography>
          <Typography variant="body2" color="text.secondary" mb={3}>
            Sign in to your operations workspace.
          </Typography>
          {demo && (
            <Alert severity="info" icon={false} sx={{ mb: 3 }}>
              <b>DEMO DATA</b> · Choose a role to explore. No password required.
            </Alert>
          )}
          {mode === "mock" && (
            <Alert severity="info" icon={false} sx={{ mb: 3 }}>
              <b>MOCK DATA</b> · Sign in with operator/operator or
              manager/manager.
            </Alert>
          )}
          <Stack spacing={2.5}>
            <TextField
              label={demo ? "Your name" : "Username"}
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              inputProps={{ maxLength: 80 }}
              autoComplete={demo ? "name" : "username"}
            />
            {!demo && (
              <TextField
                label="Password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete="current-password"
              />
            )}
            {demo && (
              <TextField
                select
                label="Workspace role"
                value={role}
                onChange={(e) => setRole(e.target.value as Role)}
              >
                <MenuItem value="OPERATOR">Operator</MenuItem>
                <MenuItem value="MANAGER">Manager</MenuItem>
              </TextField>
            )}
            <Typography variant="caption" color="text.secondary">
              Operators inspect and manage issues. Managers can also resolve
              issues and access Admin.
            </Typography>
            {session.error && (
              <ErrorNotice
                error={session.error}
                retry={() => void session.refetch()}
              />
            )}
            {login.error && <ErrorNotice error={login.error} />}
            <Button
              type="submit"
              variant="contained"
              size="large"
              endIcon={<ArrowForward />}
              disabled={login.isPending}
            >
              {login.isPending ? "Signing in…" : "Enter workspace"}
            </Button>
          </Stack>
        </Paper>
      </Stack>
    </Box>
  );
}
