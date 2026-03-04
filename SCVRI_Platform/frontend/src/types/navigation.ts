export type Role = "admin" | "analyst" | "viewer";

export type NavItem = {
  label: string;
  href: string;
  roles: Role[];
};
