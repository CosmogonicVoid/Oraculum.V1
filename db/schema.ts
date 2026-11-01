import { sqliteTable, text, integer } from 'drizzle-orm/sqlite-core';
export const accounts = sqliteTable('accounts', {
  userId: text('user_id').primaryKey(),
  state: text('state').notNull(),
  revision: integer('revision').notNull().default(0),
});
export const quotes = sqliteTable('quotes', {
  id: text('id').primaryKey(), userId: text('user_id').notNull(),
  payload: text('payload').notNull(), expires: integer('expires').notNull(),
});
export const replayAccounts = sqliteTable('replay_accounts', {
 userId: text('user_id').primaryKey(), state:text('state').notNull(), revision:integer('revision').notNull().default(0),
});
export const researchAccounts = sqliteTable('research_accounts', {
 userId:text('user_id').primaryKey(), state:text('state').notNull(), revision:integer('revision').notNull().default(0),
});
