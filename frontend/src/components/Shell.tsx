import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import {
  Alert,
  Avatar,
  Box,
  Button,
  Chip,
  Divider,
  Drawer,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Tooltip,
  Typography,
} from "@mui/material";
import {
  AdminPanelSettingsOutlined,
  AssessmentOutlined,
  Bolt,
  CloudUploadOutlined,
  DescriptionOutlined,
  FolderCopyOutlined,
  Logout,
  MapOutlined,
  Menu,
  NorthEast,
  PlaceOutlined,
} from "@mui/icons-material";
import { useDataMode, useLogout, useSession } from "../data/hooks";
import { REGIONS, REGION_INFO } from "../data/models";
import type { Region } from "../data/models";
import { useRegion } from "../data/region-context";
import { ErrorNotice } from "./common";

const links = [
  { to: "/map", label: "Map", Icon: MapOutlined },
  { to: "/files", label: "Files", Icon: FolderCopyOutlined },
  { to: "/cases", label: "Cases", Icon: DescriptionOutlined },
  { to: "/uploads", label: "Uploads", Icon: CloudUploadOutlined },
  { to: "/statistics", label: "Statistics", Icon: AssessmentOutlined },
  { to: "/admin", label: "Admin", Icon: AdminPanelSettingsOutlined },
];
export function Shell() {
  const { data: session } = useSession();
  const logout = useLogout();
  const mode = useDataMode();
  const { region, setRegion } = useRegion();
  const [mobile, setMobile] = useState(false);
  const location = useLocation();
  const navigation = (
    <Stack sx={{ height: "100%", p: 2.3, bgcolor: "#102d24", color: "#fff" }}>
      <Stack
        direction="row"
        spacing={1}
        alignItems="center"
        sx={{ p: "14px 8px 35px" }}
      >
        <Box className="brand-mark">
          <Bolt />
        </Box>
        <Typography fontSize={23} fontWeight={650} letterSpacing="-.8px">
          FileGrid<span style={{ color: "#c5e56b" }}>.</span>
        </Typography>
      </Stack>
      <Typography
        sx={{
          px: 1.5,
          mb: 1.6,
          color: "#8aa096",
          fontSize: 10,
          letterSpacing: 1.7,
        }}
      >
        OPERATIONS WORKSPACE
      </Typography>
      <Stack spacing={0.7}>
        {links
          .filter((x) => x.to !== "/admin" || session?.user.role === "MANAGER")
          .map(({ to, label, Icon }) => (
            <NavLink
              key={to}
              to={to}
              className="nav-link"
              onClick={() => setMobile(false)}
            >
              <Icon fontSize="small" />
              <span>{label}</span>
              {to === "/map" && <span className="nav-dot" />}
            </NavLink>
          ))}
      </Stack>
      <Box sx={{ flex: 1 }} />
      <Box sx={{ p: 1.5, mb: 2, border: "1px solid #355046", borderRadius: 2 }}>
        <Stack direction="row" justifyContent="space-between">
          <Bolt sx={{ color: "#c5e56b" }} fontSize="small" />
          <NorthEast sx={{ color: "#91a69b", fontSize: 16 }} />
        </Stack>
        <Typography variant="body2" mt={1}>
          A clearer view of your grid.
        </Typography>
        <Typography variant="caption" sx={{ color: "#91a69b" }}>
          Connected evidence. Better decisions.
        </Typography>
      </Box>
      <Divider sx={{ borderColor: "#355046", mb: 2 }} />
      <Typography variant="caption" sx={{ color: "#91a69b", px: 1 }}>
        FileGrid · Hackathon edition
      </Typography>
    </Stack>
  );
  return (
    <Box sx={{ display: "flex", minHeight: "100vh" }}>
      <Box
        component="aside"
        sx={{
          width: 224,
          flexShrink: 0,
          display: { xs: "none", md: "block" },
          position: "fixed",
          inset: "0 auto 0 0",
        }}
      >
        {navigation}
      </Box>
      <Drawer
        open={mobile}
        onClose={() => setMobile(false)}
        sx={{ "& .MuiDrawer-paper": { width: 224 } }}
      >
        {navigation}
      </Drawer>
      <Box sx={{ minWidth: 0, flex: 1, ml: { md: "224px" } }}>
        <Box
          component="header"
          sx={{
            bgcolor: "white",
            borderBottom: "1px solid",
            borderColor: "divider",
            px: { xs: 2, lg: 4 },
            height: 78,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 2,
          }}
        >
          <Stack direction="row" alignItems="center" spacing={1.5}>
            <IconButton
              aria-label="Open navigation"
              onClick={() => setMobile(true)}
              sx={{ display: { md: "none" } }}
            >
              <Menu />
            </IconButton>
            <Typography
              variant="body2"
              color="text.secondary"
              sx={{ display: { xs: "none", lg: "block" } }}
            >
              Workspace{" "}
              <span style={{ margin: "0 12px", color: "#bbc3bc" }}>/</span>
              <b style={{ color: "#1c3028" }}>
                {links.find((x) => x.to === location.pathname)?.label ??
                  "Overview"}
              </b>
            </Typography>
          </Stack>
          <Stack direction="row" alignItems="center" spacing={{ xs: 1, sm: 2 }}>
            <PlaceOutlined
              sx={{
                color: "text.secondary",
                display: { xs: "none", sm: "block" },
                fontSize: 19,
              }}
            />
            <FormControl size="small" sx={{ minWidth: { xs: 125, sm: 155 } }}>
              <InputLabel id="region-label">Region</InputLabel>
              <Select
                labelId="region-label"
                label="Region"
                value={region}
                onChange={(e) => setRegion(e.target.value as Region)}
              >
                {REGIONS.map((r) => (
                  <MenuItem key={r} value={r}>
                    {REGION_INFO[r].name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <Divider orientation="vertical" flexItem />
            <Avatar
              sx={{
                bgcolor: "#e7eee6",
                color: "primary.main",
                width: 35,
                height: 35,
                fontSize: 13,
              }}
            >
              {session?.user.name
                .split(" ")
                .map((x) => x[0])
                .slice(0, 2)
                .join("")}
            </Avatar>
            <Box sx={{ display: { xs: "none", sm: "block" } }}>
              <Typography variant="body2" fontWeight={600}>
                {session?.user.name}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {session?.user.role}
              </Typography>
            </Box>
            <Tooltip title="Sign out">
              <IconButton
                aria-label="Sign out"
                onClick={() => logout.mutate()}
                disabled={logout.isPending}
              >
                <Logout fontSize="small" />
              </IconButton>
            </Tooltip>
          </Stack>
        </Box>
        {mode !== "api" && (
          <Alert
            icon={false}
            severity="warning"
            sx={{
              borderRadius: 0,
              py: 0.2,
              px: { xs: 2, lg: 4 },
              bgcolor: "#f3edd9",
              color: "#6c5b26",
              "& .MuiAlert-message": { width: "100%" },
            }}
          >
            <Stack
              direction="row"
              alignItems="center"
              justifyContent="space-between"
            >
              <Typography variant="caption">
                <b>{mode === "mock" ? "MOCK DATA" : "DEMO DATA"}</b>
                <span style={{ marginLeft: 12 }}>
                  {mode === "mock"
                    ? "Contract examples served by MSW"
                    : "Illustrative network and local demo session"}
                </span>
              </Typography>
              <Chip
                size="small"
                label={mode === "mock" ? "MSW + ApiSource" : "LocalDemoSource"}
                sx={{
                  height: 21,
                  bgcolor: "#e9dfbf",
                  display: { xs: "none", sm: "flex" },
                }}
              />
            </Stack>
          </Alert>
        )}
        {logout.error && <ErrorNotice error={logout.error} />}
        <Box
          component="main"
          sx={{ px: { xs: 2, lg: 4 }, py: 3.5, maxWidth: 1800, mx: "auto" }}
        >
          <Outlet />
        </Box>
        <Box
          component="footer"
          sx={{
            px: 4,
            pb: 2,
            color: "text.secondary",
            display: "flex",
            justifyContent: "space-between",
          }}
        >
          <Typography variant="caption">
            Electricity network intelligence
          </Typography>
          <Typography variant="caption">
            Romania · {REGION_INFO[region].name}
          </Typography>
        </Box>
      </Box>
    </Box>
  );
}
export function ManagerOnly({ children }: { children: React.ReactNode }) {
  const { data } = useSession();
  return data?.user.role === "MANAGER" ? (
    children
  ) : (
    <Alert severity="warning">
      This workspace is available to managers only.
    </Alert>
  );
}
export function MapLinkButton() {
  return (
    <Button
      component={NavLink}
      to="/map"
      variant="outlined"
      startIcon={<MapOutlined />}
    >
      Open network map
    </Button>
  );
}
