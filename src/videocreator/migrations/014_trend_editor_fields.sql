-- Add horizontal subject focus ratio (0.0..1.0) to shots for smart 9:16 landscape reframing.
ALTER TABLE shots ADD COLUMN focus_x REAL;
