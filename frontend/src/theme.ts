import { createTheme } from "@mui/material/styles";

export const theme = createTheme({
  palette: {
    primary: { main: "#176747", dark: "#102d24", light: "#e6f1eb" },
    secondary: { main: "#c5e56b" },
    background: { default: "#f5f6f2", paper: "#ffffff" },
    text: { primary: "#1c3028", secondary: "#6c7971" },
    error: { main: "#c64046" },
    warning: { main: "#a66e0b" },
    divider: "#e6eae4",
  },
  typography: {
    fontFamily: 'Inter, "Segoe UI", Arial, sans-serif',
    h4: { fontWeight: 650, fontSize: "1.85rem", letterSpacing: "-.055rem" },
    h5: { fontWeight: 650, letterSpacing: "-.035rem" },
    h6: { fontWeight: 600, fontSize: "1rem" },
    button: { textTransform: "none", fontWeight: 600 },
    body2: { fontSize: ".83rem" },
  },
  shape: { borderRadius: 12 },
  components: {
    MuiButton: {
      defaultProps: { disableElevation: true },
      styleOverrides: { root: { borderRadius: 8, padding: "8px 16px" } },
    },
    MuiPaper: {
      defaultProps: { elevation: 0 },
      styleOverrides: { outlined: { borderColor: "#e3e8e0" } },
    },
    MuiChip: {
      styleOverrides: {
        root: { fontWeight: 600, fontSize: ".7rem", borderRadius: 6 },
      },
    },
    MuiTableCell: {
      styleOverrides: {
        head: {
          background: "#f9faf7",
          color: "#768077",
          fontSize: ".7rem",
          letterSpacing: ".04rem",
          textTransform: "uppercase",
          fontWeight: 600,
        },
        root: { borderColor: "#edf0eb", padding: "17px 20px" },
      },
    },
    MuiTextField: { defaultProps: { size: "small" } },
    MuiAlert: { styleOverrides: { root: { borderRadius: 8 } } },
  },
});
